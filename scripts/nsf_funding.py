"""Parse lifecycle and synopsis metadata from official NSF funding pages.

Grants.gov can continue to label an undated NSF program description as posted
after NSF has archived the program.  NSF's funding page is authoritative for
that lifecycle decision, so both the catalog enrichment step and direct NSF
source adapters use this small, offline-testable parser.
"""

from __future__ import annotations

from html.parser import HTMLParser
import re

from scripts.build_catalog import clean_text
from scripts.notice_structure import VOID_TAGS, IGNORED_TAGS


NSF_FUNDING_PAGE_PARSER_VERSION = 4
NSF_ARCHIVED_RE = re.compile(
    r"\bstatus\s*:\s*archived\b|"
    r"\barchived funding opportunity\b|"
    r"\bprogram status\s*:\s*archived\b",
    re.IGNORECASE,
)
NSF_REPLACEMENT_RE = re.compile(
    r"\b(?:see|replaced by)\s+((?:PD|NSF)\s*\d{2}-[A-Z0-9]+)\b",
    re.IGNORECASE,
)
BLOCK_TAGS = {
    "address",
    "article",
    "blockquote",
    "br",
    "div",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "ol",
    "p",
    "section",
    "table",
    "tr",
    "ul",
}


class _NsfFundingPageParser(HTMLParser):
    """Collect visible page text and the structured NSF synopsis field."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.capture_depth = 0
        self.skip_depth = 0
        self.visible_parts: list[str] = []
        self.synopsis_parts: list[str] = []
        self.frames = []
        self.main_parts = []
        self.saw_main = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = attributes.get("class", "").split()
        parent = self.frames[-1] if self.frames else {}
        ignored = parent.get("ignored", False) or tag in IGNORED_TAGS or bool(re.search(
            r"(?:^|[\s_-])(?:sidebar|related-opportunities|related-programs)(?:$|[\s_-])",
            attributes.get("class", "") + " " + attributes.get("id", ""), re.I))
        frame = {"tag": tag, "ignored": ignored,
            "capture": not ignored and (parent.get("capture", False) or "field-funding-synopsis" in classes),
            "main": parent.get("main", False) or tag == "main"}
        if tag not in VOID_TAGS:
            self.frames.append(frame)
        self.saw_main = self.saw_main or tag == "main"
        self.capture_depth = int(frame["capture"])
        self.skip_depth = int(ignored)
        if ignored:
            return
        if tag in BLOCK_TAGS:
            self.append("\n", frame)
        if tag == "li" and self.capture_depth:
            self.synopsis_parts.append("• ")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        frame = self.frames[-1] if self.frames else {}
        if tag in BLOCK_TAGS and not frame.get("ignored"):
            self.append("\n", frame)
        index = next((i for i in range(len(self.frames) - 1, -1, -1) if self.frames[i]["tag"] == tag), None)
        if index is not None:
            del self.frames[index:]
        frame = self.frames[-1] if self.frames else {}
        self.capture_depth, self.skip_depth = int(frame.get("capture", False)), int(frame.get("ignored", False))

    def append(self, value, frame):
        self.visible_parts.append(value)
        if frame.get("main"):
            self.main_parts.append(value)
        if frame.get("capture"):
            self.synopsis_parts.append(value)

    def handle_data(self, data):
        if self.skip_depth:
            return
        value = re.sub(r"\s+", " ", data)
        self.append(value, self.frames[-1] if self.frames else {})


def parse_nsf_funding_page(
    html: str,
    *,
    require_synopsis: bool = True,
) -> dict:
    """Return the official page's synopsis, lifecycle, and replacement id."""
    parser = _NsfFundingPageParser()
    parser.feed(str(html or ""))
    parser.close()

    visible_text = clean_text("".join(parser.main_parts if parser.saw_main else parser.visible_parts)) or ""
    archived = bool(NSF_ARCHIVED_RE.search(visible_text))
    synopsis = clean_text("".join(parser.synopsis_parts)) or ""
    synopsis = re.sub(r"^Synopsis(?:\s+|$)", "", synopsis, count=1).strip()
    if len(synopsis) < 100 and require_synopsis:
        raise RuntimeError("official NSF page did not contain a usable synopsis")
    replacement = NSF_REPLACEMENT_RE.search(visible_text) if archived else None
    replacement_number = None
    if replacement:
        replacement_number = re.sub(
            r"\s+", "-", replacement.group(1).upper()
        )

    return {
        "text": synopsis[:12000],
        "status": (
            "archived"
            if archived
            else "current"
            if len(synopsis) >= 100
            else "not_archived"
        ),
        "replacement_opportunity_number": replacement_number,
    }


def extract_nsf_synopsis(html: str) -> str:
    """Compatibility wrapper for callers that only need synopsis text."""
    return parse_nsf_funding_page(html)["text"]
