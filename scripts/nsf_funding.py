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


NSF_FUNDING_PAGE_PARSER_VERSION = 3
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

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "template"}:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return

        classes = dict(attrs).get("class", "").split()
        if not self.capture_depth and "field-funding-synopsis" in classes:
            self.capture_depth = 1
        elif self.capture_depth:
            self.capture_depth += 1

        if tag in BLOCK_TAGS:
            self.visible_parts.append("\n")
            if self.capture_depth:
                self.synopsis_parts.append("\n")
        if tag == "li" and self.capture_depth:
            self.synopsis_parts.append("• ")

    def handle_startendtag(self, tag, attrs):
        if not self.skip_depth and tag in BLOCK_TAGS:
            self.visible_parts.append("\n")
            if self.capture_depth:
                self.synopsis_parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "template"}:
            if self.skip_depth:
                self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag in BLOCK_TAGS:
            self.visible_parts.append("\n")
            if self.capture_depth:
                self.synopsis_parts.append("\n")
        if self.capture_depth:
            self.capture_depth -= 1

    def handle_data(self, data):
        if self.skip_depth:
            return
        value = re.sub(r"\s+", " ", data)
        self.visible_parts.append(value)
        if self.capture_depth:
            self.synopsis_parts.append(value)


def parse_nsf_funding_page(
    html: str,
    *,
    require_synopsis: bool = True,
) -> dict:
    """Return the official page's synopsis, lifecycle, and replacement id."""
    parser = _NsfFundingPageParser()
    parser.feed(str(html or ""))
    parser.close()

    visible_text = clean_text("".join(parser.visible_parts)) or ""
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
