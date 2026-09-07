"""Bounded HTML notice blocks; full text is private extraction context only."""
from html.parser import HTMLParser
import re


STRUCTURE_VERSION = "notice-blocks-2"
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
IGNORED_TAGS = {"head", "script", "style", "noscript", "template", "svg", "nav", "aside", "footer"}
BLOCK_TAGS = {"p", "li", "div", "section", "article", "blockquote", "dt", "dd", "address", "br"}


def clean(value):
    return re.sub(r"\s+", " ", value.replace("\x00", " ").replace("\u00ad", "")).strip()


class NoticeHTMLParser(HTMLParser):
    """Retain short fields and table ownership, excluding scoped page furniture.

    Public evidence consumes compact references to these blocks. Cell order,
    empty cells and spans are retained rather than inferred from date positions.
    """

    def __init__(self, *, nsf_submission_component=False):
        super().__init__(convert_charrefs=True)
        self.blocks, self.buffer, self.frames, self.tables = [], [], [], []
        self.current_section, self.current_anchor = "Official notice", None
        self.headings, self.heading = [], None
        self.kind, self.span = "paragraph", None
        self.context = []
        self.row, self.cell = None, None
        self.table_count = 0
        self.nested_table_depth = 0
        self.diagnostics = []
        self.nsf_submission_component = nsf_submission_component
        self.submission_components = 0

    def ignored(self):
        return bool(self.frames and self.frames[-1][1])

    def emit(self, text, kind, **extra):
        # Table cells are already normalized individually. Preserve separators
        # around empty cells so the derived text offsets retain their columns.
        text = text if kind == "table_row" else clean(text)
        if text or kind == "table_row":
            self.blocks.append({"text": text, "section": self.current_section,
                "anchor": self.current_anchor, "kind": kind,
                "heading_path": list(self.headings), "reading_order": len(self.blocks),
                "block_id": f"html-{len(self.blocks) + 1}", "source_position": self.span,
                "ancestors": list(self.context),
                **extra})
            if any('program-due-dates' in a.get('class', '').split() for a in self.context):
                self.blocks[-1]['source_component'] = 'nsf_submission_fields'

    def flush(self):
        self.emit("".join(self.buffer), self.kind)
        self.buffer, self.span, self.context = [], None, []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        # HTML permits omitted cell/row end tags. Close only siblings in the
        # current table; nested tables retain their own uncertainty marker.
        if not self.ignored() and not self.nested_table_depth:
            if tag in {"td", "th", "tr"} and self.cell is not None:
                self.finish_cell()
                position = next((i for i in range(len(self.frames) - 1, -1, -1)
                                 if self.frames[i][0] in {"td", "th"}), None)
                if position is not None:
                    del self.frames[position:]
            if tag == "tr" and self.row is not None:
                self.finish_row()
                position = next((i for i in range(len(self.frames) - 1, -1, -1)
                                 if self.frames[i][0] == "tr"), None)
                if position is not None:
                    del self.frames[position:]
        ignored = self.ignored() or tag in IGNORED_TAGS or attrs.get("role") in {"navigation", "banner"}
        component = (self.nsf_submission_component and tag == 'div'
                     and 'program-due-dates' in attrs.get('class', '').split())
        if component:
            self.submission_components += 1
            first_excluded = next((name for name, excluded, _ in self.frames if excluded), None)
            if first_excluded == 'aside' and not any(
                name in IGNORED_TAGS - {'aside'} or native.get('role') in {'navigation', 'banner'}
                or re.search(r'(?:^|[\s_-])(?:toc|cookie-banner|table-of-contents)(?:$|[\s_-])',
                             native.get('class', '') + ' ' + native.get('id', ''), re.I)
                for name, _, native in self.frames):
                # NSF's current-program submission component is intentionally
                # in an aside. Other sidebar text stays excluded, including
                # lifecycle labels for unrelated programs and navigation.
                ignored = False
        classes = " ".join((attrs.get("class", ""), attrs.get("id", "")))
        ignored = ignored or bool(re.search(r"(?:^|[\s_-])(?:toc|cookie-banner|table-of-contents)(?:$|[\s_-])", classes, re.I))
        if ignored and not self.ignored():
            self.flush()
        if tag not in VOID_TAGS:
            native = {key: value for key, value in attrs.items() if key in {
                "id", "class", "role", "data-index", "data-element-id", "data-section-code", "data-element-type", "data-element-has-label"}}
            if self.nsf_submission_component and {'program-due-dates__due-date-item', 'program-due-dates__item'}.intersection(attrs.get('class', '').split()):
                native['source_position'] = self.getpos()
            self.frames.append((tag, ignored, native))
        if ignored:
            return
        if self.cell is not None:
            if tag == "br":
                self.cell["parts"].append(" ")
            elif tag == "table":
                self.cell["nested_table"] = True
                self.nested_table_depth += 1
                if "nested_table_structure" not in self.diagnostics:
                    self.diagnostics.append("nested_table_structure")
            return
        if tag == "table":
            self.flush()
            self.table_count += 1
            self.tables.append({"id": f"table-{self.table_count}", "row": 0, "headers": []})
        elif tag == "tr" and self.tables:
            if self.row is not None:
                self.finish_row()
            self.flush()
            self.row = []
            self.span = self.getpos()
            self.context = [{"tag": name, **native} for name, excluded, native in self.frames if native and not excluded]
        elif tag in {"td", "th"} and self.row is not None:
            def span(name):
                value = attrs.get(name, "1")
                return int(value) if value.isdigit() and 1 <= int(value) <= 100 else None
            self.cell = {"parts": [], "header": tag == "th", "colspan": span("colspan"),
                "rowspan": span("rowspan"), "scope": attrs.get("scope"), "source_position": self.getpos()}
        elif re.fullmatch(r"h[1-6]", tag):
            self.flush()
            self.span = self.getpos()
            self.heading = {"tag": tag, "parts": [], "anchor": attrs.get("id")}
        elif tag in BLOCK_TAGS:
            self.flush()
            self.kind = "list_item" if tag == "li" else "field" if tag in {"dt", "dd"} else "paragraph"

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def finish_cell(self):
        if self.cell is not None:
            self.cell["text"] = clean("".join(self.cell.pop("parts")))
            self.cell["column"] = sum(c.get("colspan") or 1 for c in self.row)
            self.row.append(self.cell)
            self.cell = None

    def finish_row(self):
        self.finish_cell()
        if self.row is not None and self.tables:
            table = self.tables[-1]
            cells = self.row
            header = bool(cells) and all(c["header"] for c in cells)
            self.emit(" | ".join(c["text"] for c in cells), "table_row", table_id=table["id"],
                row=table["row"], cells=cells, header_rows=list(table["headers"]), is_header=header)
            if header:
                table["headers"].append(cells)
            table["row"] += 1
        self.row = None

    def handle_endtag(self, tag):
        ignored = self.ignored()
        # Match actual elements, including optional-end-tag HTML; a void tag
        # never changes ownership depth.
        position = next((i for i in range(len(self.frames) - 1, -1, -1) if self.frames[i][0] == tag), None)
        if position is not None:
            del self.frames[position:]
        if ignored:
            return
        if self.nested_table_depth:
            if tag == "table":
                self.nested_table_depth -= 1
            return
        if tag in {"tr", "table"}:
            self.finish_cell()
        if tag in {"td", "th"}:
            self.finish_cell()
        elif self.cell is not None:
            return
        elif tag == "tr":
            self.finish_row()
        elif tag == "table":
            self.finish_row()
            if self.tables:
                self.tables.pop()
        elif self.heading and tag == self.heading["tag"]:
            heading = clean("".join(self.heading["parts"]))
            level = int(tag[1])
            self.headings = self.headings[:level - 1] + [heading]
            self.current_section = heading[:180] or "Official notice"
            self.current_anchor = self.heading["anchor"]
            self.emit(heading, "heading")
            self.heading = None
            self.span = None
        elif tag in BLOCK_TAGS:
            self.flush()

    def handle_data(self, data):
        if self.ignored():
            return
        if self.cell is not None:
            self.cell["parts"].append(data)
        elif self.heading:
            self.heading["parts"].append(data)
        else:
            if self.span is None:
                self.span = self.getpos()
                self.context = [{"tag": tag, **attrs} for tag, ignored, attrs in self.frames if attrs and not ignored]
            self.buffer.append(data)

    def close(self):
        super().close()
        if self.row is not None or self.tables or self.heading:
            self.diagnostics.append("incomplete_field_structure")
        self.finish_row()
        self.flush()
