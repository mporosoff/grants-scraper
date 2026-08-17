"""Build citation-backed evidence from official funding notices.

Phase 1.5 identifies the best official notice or agency page. Phase 3 reads a
bounded number of those sources during the scheduled GitHub Actions refresh,
extracts high-value facts with page/section citations, and merges only compact
derived evidence into the browser catalog.

Raw PDFs and HTML are never committed. The cache stores HTTP validators,
document hashes, short evidence quotes, extracted facts, and a small version
history so unchanged notices can be reused and amended notices can be detected.
All prose-derived facts remain explicitly machine-extracted and
verification-required; structured Grants.gov fields retain authority for
filtering and sorting.
"""

import argparse
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
import hashlib
import io
import ipaddress
import json
from pathlib import Path
import re
import socket
import tempfile
import time
from urllib.parse import urljoin, urlparse

from pypdf import PdfReader
import requests

from scripts.build_catalog import (
    build_search_index,
    clean_text,
    iso_utc,
    write_catalog,
)
from scripts.enrich_catalog import read_catalog
from scripts import program_areas


EVIDENCE_SCHEMA_VERSION = 1
DEFAULT_CATALOG = Path("data/opportunities.js")
DEFAULT_CACHE = Path("data/document_evidence.json")
DEFAULT_SUBTOPIC_CACHE = Path("data/subtopic_records.json")
USER_AGENT = "Funding-Finder-Document-Evidence/1.0"
MAX_DOWNLOAD_BYTES = 30 * 1024 * 1024
MAX_PDF_PAGES = 250
MAX_PAGE_CHARS = 30_000
MAX_FACTS = 36
MAX_PROGRAM_AREAS = 14
MAX_QUOTE_CHARS = 360
MAX_VERSION_HISTORY = 6

MONTH_PATTERN = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
    r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|"
    r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
DATE_RE = re.compile(
    rf"\b(?:{MONTH_PATTERN}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?"
    rf"(?:\s*,)?\s+20\d{{2}}|\d{{1,2}}[/-]\d{{1,2}}[/-]"
    rf"(?:20)?\d{{2}})\b",
    re.I,
)
TIME_RE = re.compile(
    r"\b(\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?))"
    r"(?:\s+([A-Z]{2,4}|Eastern|Central|Mountain|Pacific)"
    r"(?:\s+(?:Time|Standard Time|Daylight Time))?)?",
    re.I,
)
DEADLINE_CUE_RE = re.compile(
    r"\b(?:deadline|due|submit(?:ted)?|submission|received|closing|"
    r"no later than|must be filed|applications? by|proposals? by)\b",
    re.I,
)
DEADLINE_KINDS = (
    (
        "letter_of_intent",
        "Letter of intent deadline",
        re.compile(r"\b(?:letter\s+of\s+intent|LOI)\b", re.I),
    ),
    (
        "concept_paper",
        "Concept paper deadline",
        re.compile(r"\bconcept\s+paper\b", re.I),
    ),
    (
        "white_paper",
        "White paper deadline",
        re.compile(r"\bwhite\s+paper\b", re.I),
    ),
    (
        "preapplication",
        "Preapplication deadline",
        re.compile(r"\bpre[\s-]?application\b", re.I),
    ),
    (
        "preproposal",
        "Preproposal deadline",
        re.compile(
            r"\b(?:pre[\s-]?proposal|preliminary\s+proposal)\b",
            re.I,
        ),
    ),
    (
        "application",
        "Full application deadline",
        re.compile(
            r"\b(?:full\s+(?:application|proposal)|final\s+proposal|"
            r"application\s+deadline|proposal\s+deadline|applications?|"
            r"proposals?)\b",
            re.I,
        ),
    ),
)
MONEY_RE = re.compile(
    r"\$\s*(\d[\d,]*(?:\.\d+)?)\s*"
    r"(thousand|million|billion|[KMB])?\b",
    re.I,
)
AWARD_CUE_RE = re.compile(
    r"\b(?:per[\s-]?award|each\s+award|individual\s+award|award\s+"
    r"(?:amount|range|floor|ceiling|maximum|minimum)|maximum\s+award|"
    r"minimum\s+award|grant\s+amount)\b",
    re.I,
)
PROGRAM_TOTAL_RE = re.compile(
    r"\b(?:total\s+(?:program\s+)?funding|total\s+available|"
    r"aggregate\s+funding|program\s+ceiling)\b",
    re.I,
)
EXPECTED_AWARDS_RE = re.compile(
    r"\b(?:anticipat(?:e|es|ed)|expect(?:s|ed)?|intend(?:s|ed)?)"
    r"(?:\s+to)?\s+(?:make|fund|award|issue)?\s*"
    r"(?:approximately|about|up to)?\s*(\d{1,3})\s+"
    r"(?:awards?|grants?)\b",
    re.I,
)
DURATION_RE = re.compile(
    r"\b(?:period\s+of\s+performance|project\s+(?:period|duration)|"
    r"award\s+(?:period|duration))\D{0,90}?"
    r"(?:up\s+to\s+|not\s+to\s+exceed\s+)?(\d{1,3})\s*"
    r"(months?|years?)\b",
    re.I,
)
PAGE_LIMIT_RE = re.compile(
    r"\b(?:(\d{1,3})[\s-]+page\s+limit|limited\s+to\s+"
    r"(\d{1,3})\s+pages?|not\s+(?:to\s+)?exceed\s+"
    r"(\d{1,3})\s+pages?)\b",
    re.I,
)
COST_SHARE_RE = re.compile(
    r"\b(?:cost[\s-]?shar(?:e|ing)|matching\s+(?:funds?|requirement)|"
    r"recipient\s+share)\b",
    re.I,
)
LIMITED_SUBMISSION_RE = re.compile(
    r"(?:\blimit(?:ed|s)?\s+(?:to\s+)?"
    r"(?:one|two|three|1|2|3)\s+(?:application|proposal|submission)s?\b|"
    r"\b(?:one|two|three|1|2|3)\s+(?:application|proposal|submission)s?"
    r".{0,140}\bper\s+(?:institution|organization|applicant|university)\b)",
    re.I | re.S,
)
STATUS_SIGNAL_PATTERNS = (
    (
        "cancelled",
        "Cancellation or withdrawal language",
        re.compile(r"\b(?:cancelled|canceled|withdrawn)\b", re.I),
    ),
    (
        "superseded",
        "Superseded notice language",
        re.compile(r"\bsuperseded\s+by\b|\bthis\s+notice\s+supersedes\b", re.I),
    ),
    (
        "amended",
        "Amendment or revision language",
        re.compile(
            r"\b(?:amended|revised)\s+(?:notice|NOFO|FOA|solicitation)\b",
            re.I,
        ),
    ),
    (
        "recurring",
        "Recurring or open-until-superseded language",
        re.compile(
            r"\b(?:open\s+until\s+superseded|recurring\s+(?:program|notice)|"
            r"applications?\s+(?:are\s+)?accepted\s+on\s+a\s+rolling\s+basis)\b",
            re.I,
        ),
    ),
)
APPLICATION_COMPONENTS = {
    "Budget narrative": re.compile(r"\bbudget\s+narrative\b", re.I),
    "Biosketch or biographical sketch": re.compile(
        r"\b(?:biosketch|biographical\s+sketch)\b",
        re.I,
    ),
    "Current and pending support": re.compile(
        r"\bcurrent\s+and\s+pending\s+support\b",
        re.I,
    ),
    "Data management plan": re.compile(
        r"\bdata\s+management(?:\s+and\s+sharing)?\s+plan\b",
        re.I,
    ),
    "Evaluation plan": re.compile(r"\bevaluation\s+plan\b", re.I),
    "Letters of support": re.compile(
        r"\bletters?\s+of\s+(?:support|commitment)\b",
        re.I,
    ),
    "Logic model": re.compile(r"\blogic\s+model\b", re.I),
    "Project narrative": re.compile(r"\bproject\s+narrative\b", re.I),
    "Work plan": re.compile(r"\bwork\s+plan\b", re.I),
}


def utc_now():
    return datetime.now(timezone.utc)


def empty_cache():
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "generated_at": None,
        "records": {},
    }


def read_cache(path):
    path = Path(path)
    if not path.exists():
        return empty_cache()
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if parsed.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        return empty_cache()
    if not isinstance(parsed.get("records"), dict):
        raise RuntimeError(f"{path} does not contain a document record map.")
    return parsed


def write_cache(cache, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.stem}-",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary_path = Path(output.name)
            json.dump(cache, output, ensure_ascii=False, separators=(",", ":"))
            output.write("\n")
        temporary_path.replace(path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def clean_document_text(value):
    text = str(value or "").replace("\u0000", " ").replace("\u00ad", "")
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_document_date(value):
    text = re.sub(
        r"(\d)(?:st|nd|rd|th)\b",
        r"\1",
        str(value or ""),
        flags=re.I,
    )
    text = re.sub(r"\s*,\s*", " ", text)
    text = re.sub(r"\bSept\b", "Sep", text, flags=re.I)
    text = text.replace(".", "").strip()
    for pattern in (
        "%B %d %Y",
        "%b %d %Y",
        "%m/%d/%Y",
        "%m-%d-%Y",
        "%m/%d/%y",
        "%m-%d-%y",
    ):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            continue
    return None


def parse_money(value, unit=None):
    try:
        amount = float(str(value).replace(",", ""))
    except ValueError:
        return None
    multiplier = {
        "k": 1_000,
        "thousand": 1_000,
        "m": 1_000_000,
        "million": 1_000_000,
        "b": 1_000_000_000,
        "billion": 1_000_000_000,
    }.get(str(unit or "").casefold(), 1)
    result = round(amount * multiplier)
    return result if result > 0 else None


def format_money(value):
    return f"${int(value):,}" if value else "not listed"


def context_quote(text, start, end, maximum=MAX_QUOTE_CHARS):
    left = max(0, start - maximum // 2)
    right = min(len(text), end + maximum // 2)
    excerpt = re.sub(r"\s+", " ", text[left:right]).strip(" \t\n-;")
    if left:
        excerpt = f"…{excerpt}"
    if right < len(text):
        excerpt = f"{excerpt}…"
    return excerpt[: maximum - 1].rstrip() + (
        "…" if len(excerpt) >= maximum else ""
    )


class NoticeHTMLParser(HTMLParser):
    """Collect readable HTML blocks with their nearest heading."""

    BLOCK_TAGS = {
        "p",
        "li",
        "td",
        "th",
        "div",
        "section",
        "article",
        "br",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self.buffer = []
        self.current_section = "Official notice"
        self.current_anchor = None
        self.heading_tag = None
        self.heading_buffer = []
        self.heading_anchor = None
        self.ignored_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.casefold()
        attributes = dict(attrs)
        if tag in {"script", "style", "noscript", "svg"}:
            self.ignored_depth += 1
            return
        if self.ignored_depth:
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._flush()
            self.heading_tag = tag
            self.heading_buffer = []
            self.heading_anchor = attributes.get("id")
        elif tag in self.BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag):
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "svg"}:
            self.ignored_depth = max(0, self.ignored_depth - 1)
            return
        if self.ignored_depth:
            return
        if tag == self.heading_tag:
            heading = clean_document_text(" ".join(self.heading_buffer))
            if heading:
                self.current_section = heading[:180]
                self.current_anchor = self.heading_anchor
            self.heading_tag = None
            self.heading_buffer = []
            self.heading_anchor = None
        elif tag in self.BLOCK_TAGS:
            self._flush()

    def handle_data(self, data):
        if self.ignored_depth:
            return
        if self.heading_tag:
            self.heading_buffer.append(data)
        else:
            self.buffer.append(data)

    def close(self):
        super().close()
        self._flush()

    def _flush(self):
        text = clean_document_text(" ".join(self.buffer))
        self.buffer = []
        if len(text) >= 20:
            self.blocks.append(
                {
                    "text": text,
                    "section": self.current_section,
                    "anchor": self.current_anchor,
                }
            )


def extract_pdf_pages(content):
    reader = PdfReader(io.BytesIO(content), strict=False)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:  # noqa: BLE001 - extraction warning below
            pass
    total_pages = len(reader.pages)
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        if index > MAX_PDF_PAGES:
            break
        try:
            text = clean_document_text(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - retain other readable pages
            text = ""
        if text:
            pages.append(
                {
                    "page": index,
                    "section": None,
                    "anchor": None,
                    "text": text[:MAX_PAGE_CHARS],
                }
            )
    return pages, {
        "method": "pypdf",
        "page_count": total_pages,
        "pages_read": min(total_pages, MAX_PDF_PAGES),
        "pages_with_text": len(pages),
        "truncated": total_pages > MAX_PDF_PAGES,
    }


def extract_html_sections(content):
    decoded = content.decode("utf-8", errors="replace")
    parser = NoticeHTMLParser()
    parser.feed(decoded)
    parser.close()
    grouped = []
    for block in parser.blocks:
        if (
            grouped
            and grouped[-1]["section"] == block["section"]
            and grouped[-1]["anchor"] == block["anchor"]
            and len(grouped[-1]["text"]) + len(block["text"]) < MAX_PAGE_CHARS
        ):
            grouped[-1]["text"] += f"\n{block['text']}"
        else:
            grouped.append(
                {
                    "page": None,
                    "section": block["section"],
                    "anchor": block["anchor"],
                    "text": block["text"],
                }
            )
    return grouped, {
        "method": "html",
        "page_count": None,
        "pages_read": None,
        "pages_with_text": len(grouped),
        "truncated": False,
    }


def content_kind(content, content_type, name, final_url):
    media = str(content_type or "").split(";", 1)[0].strip().casefold()
    suffix_text = f"{name or ''} {final_url or ''}".casefold()
    if content[:5] == b"%PDF-" or media == "application/pdf" or ".pdf" in suffix_text:
        return "pdf"
    if media in {"text/html", "application/xhtml+xml"} or re.search(
        br"^\s*<(?:!doctype\s+html|html)\b",
        content[:500],
        re.I,
    ):
        return "html"
    if media.startswith("text/"):
        return "text"
    return "unsupported"


def extract_containers(content, content_type, name, final_url):
    kind = content_kind(content, content_type, name, final_url)
    if kind == "pdf":
        containers, extraction = extract_pdf_pages(content)
    elif kind == "html":
        containers, extraction = extract_html_sections(content)
    elif kind == "text":
        containers = [
            {
                "page": None,
                "section": "Official notice",
                "anchor": None,
                "text": clean_document_text(
                    content.decode("utf-8", errors="replace")
                )[:MAX_PAGE_CHARS],
            }
        ]
        extraction = {
            "method": "text",
            "page_count": None,
            "pages_read": None,
            "pages_with_text": int(bool(containers[0]["text"])),
            "truncated": False,
        }
    else:
        raise RuntimeError(
            f"Unsupported official-document content type: {content_type or 'unknown'}"
        )
    extraction["content_kind"] = kind
    extraction["text_characters"] = sum(
        len(container["text"]) for container in containers
    )
    return containers, extraction


def citation_for(container, document, start, end, extracted_at):
    url = document["url"]
    if container.get("page"):
        citation_url = f"{url}#page={container['page']}"
        location = f"page {container['page']}"
    elif container.get("anchor"):
        citation_url = f"{url}#{container['anchor']}"
        location = f"section “{container['section']}”"
    else:
        citation_url = url
        location = f"section “{container.get('section') or 'Official notice'}”"
    return {
        "document_url": url,
        "citation_url": citation_url,
        "document_name": document.get("name"),
        "sha256": document["sha256"],
        "page": container.get("page"),
        "section": container.get("section"),
        "location": location,
        "quote": context_quote(container["text"], start, end),
        "extracted_at": extracted_at,
    }


def evidence_id(opportunity_id, fact_type, label, value, citation):
    payload = json.dumps(
        {
            "opportunity_id": opportunity_id,
            "type": fact_type,
            "label": label,
            "value": value,
            "page": citation.get("page"),
            "section": citation.get("section"),
            "quote": citation.get("quote"),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"evidence-{opportunity_id}-{digest}"


def make_fact(
    opportunity_id,
    fact_type,
    label,
    value,
    display_value,
    citation,
    **extra,
):
    fact = {
        "id": evidence_id(
            opportunity_id,
            fact_type,
            label,
            value,
            citation,
        ),
        "type": fact_type,
        "label": label,
        "value": value,
        "display_value": display_value,
        "confidence": "machine_extracted_needs_verification",
        "citation": citation,
    }
    fact.update(extra)
    return fact


def deadline_kind(context, date_offset=None):
    matches = []
    for kind, label, pattern in DEADLINE_KINDS:
        for match in pattern.finditer(context):
            distance = (
                abs(((match.start() + match.end()) // 2) - date_offset)
                if date_offset is not None
                else match.start()
            )
            matches.append((distance, match.start(), kind, label))
    if not matches:
        return None
    _, _, kind, label = min(matches, key=lambda item: (item[0], item[1]))
    return kind, label


def extract_deadlines(opportunity_id, containers, document, extracted_at):
    facts = []
    seen = set()
    for container in containers:
        text = container["text"]
        for match in DATE_RE.finditer(text):
            window_start = max(0, match.start() - 230)
            window_end = min(len(text), match.end() + 230)
            context = text[window_start:window_end]
            kind_result = deadline_kind(
                context,
                match.start() - window_start,
            )
            if not kind_result or not DEADLINE_CUE_RE.search(context):
                continue
            parsed = parse_document_date(match.group(0))
            if not parsed:
                continue
            kind, label = kind_result
            identity = (kind, parsed)
            if identity in seen:
                continue
            seen.add(identity)
            time_match = TIME_RE.search(context)
            deadline_time = clean_text(time_match.group(1)) if time_match else None
            timezone_value = (
                clean_text(time_match.group(2))
                if time_match and time_match.group(2)
                else None
            )
            required = bool(
                re.search(
                    r"\b(?:must|required|shall|due|no later than)\b",
                    context,
                    re.I,
                )
            )
            citation = citation_for(
                container,
                document,
                match.start(),
                match.end(),
                extracted_at,
            )
            display = parsed
            if deadline_time:
                display += f" · {deadline_time}"
            if timezone_value:
                display += f" {timezone_value}"
            facts.append(
                make_fact(
                    opportunity_id,
                    "deadline",
                    label,
                    parsed,
                    display,
                    citation,
                    deadline_kind=kind,
                    date=parsed,
                    time=deadline_time,
                    timezone=timezone_value,
                    required=required,
                )
            )
            if len(facts) >= 12:
                return facts
    return facts


def extract_award_range(opportunity_id, containers, document, extracted_at):
    for container in containers:
        text = container["text"]
        for cue in AWARD_CUE_RE.finditer(text):
            start = max(0, cue.start() - 120)
            end = min(len(text), cue.end() + 260)
            context = text[start:end]
            if PROGRAM_TOTAL_RE.search(context):
                continue
            amounts = [
                parse_money(match.group(1), match.group(2))
                for match in MONEY_RE.finditer(context)
            ]
            amounts = [amount for amount in amounts if amount]
            if not amounts:
                continue
            minimum = None
            maximum = None
            if len(amounts) >= 2 and re.search(
                r"\b(?:between|range|from)\b.{0,100}\b(?:and|to|through|-)\b",
                context,
                re.I | re.S,
            ):
                minimum, maximum = min(amounts[:2]), max(amounts[:2])
            elif re.search(
                r"\b(?:up\s+to|maximum|not\s+(?:to\s+)?exceed|ceiling)\b",
                context,
                re.I,
            ):
                maximum = amounts[0]
            elif re.search(r"\bminimum|floor\b", context, re.I):
                minimum = amounts[0]
            else:
                maximum = amounts[0]
            display = (
                f"{format_money(minimum)}–{format_money(maximum)}"
                if minimum and maximum and minimum != maximum
                else f"Up to {format_money(maximum)}"
                if maximum
                else f"From {format_money(minimum)}"
            )
            citation = citation_for(
                container,
                document,
                start + max(0, cue.start() - start),
                min(len(text), end),
                extracted_at,
            )
            return make_fact(
                opportunity_id,
                "award_range",
                "Per-award amount",
                {"minimum": minimum, "maximum": maximum},
                display,
                citation,
            )
    return None


def first_pattern_fact(
    opportunity_id,
    containers,
    document,
    extracted_at,
    *,
    pattern,
    fact_type,
    label,
    value_builder,
    display_builder,
):
    for container in containers:
        match = pattern.search(container["text"])
        if not match:
            continue
        value = value_builder(match)
        if value in (None, "", [], {}):
            continue
        citation = citation_for(
            container,
            document,
            match.start(),
            match.end(),
            extracted_at,
        )
        return make_fact(
            opportunity_id,
            fact_type,
            label,
            value,
            display_builder(value),
            citation,
        )
    return None


def extract_cost_share(opportunity_id, containers, document, extracted_at):
    for container in containers:
        text = container["text"]
        for match in COST_SHARE_RE.finditer(text):
            start = max(0, match.start() - 150)
            end = min(len(text), match.end() + 220)
            context = text[start:end]
            not_required = bool(
                re.search(
                    r"\b(?:not|required\s+is\s+not|no)\b.{0,45}"
                    r"(?:cost[\s-]?sharing|match)",
                    context,
                    re.I | re.S,
                )
                or re.search(
                    r"(?:cost[\s-]?sharing|match).{0,45}\bnot\s+required\b",
                    context,
                    re.I | re.S,
                )
            )
            required = bool(
                re.search(
                    r"(?:cost[\s-]?sharing|matching).{0,70}\b"
                    r"(?:is|required|must|minimum)\b",
                    context,
                    re.I | re.S,
                )
            ) and not not_required
            if not (not_required or required):
                continue
            value = not not_required
            citation = citation_for(
                container,
                document,
                match.start(),
                match.end(),
                extracted_at,
            )
            return make_fact(
                opportunity_id,
                "cost_share",
                "Cost sharing",
                value,
                "Required" if value else "Not required",
                citation,
            )
    return None


def extract_heading_excerpt(
    opportunity_id,
    containers,
    document,
    extracted_at,
    *,
    fact_type,
    label,
    heading_pattern,
):
    for container in containers:
        text = container["text"]
        section = container.get("section") or ""
        match = heading_pattern.search(section) or heading_pattern.search(text)
        if not match:
            continue
        if re.search(r"\btable\s+of\s+contents\b", text[:300], re.I):
            continue
        start = match.start() if match.re is heading_pattern and match.string == text else 0
        end = min(len(text), start + 420)
        citation = citation_for(
            container,
            document,
            start,
            end,
            extracted_at,
        )
        excerpt = re.sub(r"\s+", " ", text[start:end]).strip()
        return make_fact(
            opportunity_id,
            fact_type,
            label,
            excerpt[:320],
            excerpt[:220] + ("…" if len(excerpt) > 220 else ""),
            citation,
        )
    return None


def extract_repeated_signals(
    opportunity_id,
    containers,
    document,
    extracted_at,
    *,
    patterns,
    fact_type,
    maximum,
):
    facts = []
    seen = set()
    for label, pattern in patterns:
        for container in containers:
            match = pattern.search(container["text"])
            if not match or label in seen:
                continue
            seen.add(label)
            citation = citation_for(
                container,
                document,
                match.start(),
                match.end(),
                extracted_at,
            )
            facts.append(
                make_fact(
                    opportunity_id,
                    fact_type,
                    label,
                    label,
                    label,
                    citation,
                )
            )
            break
        if len(facts) >= maximum:
            break
    return facts


def extract_program_areas(containers, document, extracted_at, maximum=MAX_PROGRAM_AREAS):
    """Detect controlled program-area terms that actually appear in the notice.

    Returns a list of ``{"label", "topics", "citation"}`` for each program area
    found in the official document text. These are inferred discoverability
    signals -- kept separate from official ``facts`` -- that make an opaque
    umbrella FOA findable by topic. Each hit carries a page/section citation, so
    it is evidence-backed and auditable in the evidence cache.
    """
    hits = []
    seen = set()
    for label, topics, pattern in program_areas.ENTRIES:
        if label in seen:
            continue
        for container in containers:
            match = pattern.search(container["text"])
            if not match:
                continue
            citation = citation_for(
                container,
                document,
                match.start(),
                match.end(),
                extracted_at,
            )
            hits.append({"label": label, "topics": list(topics), "citation": citation})
            seen.add(label)
            break
        if len(hits) >= maximum:
            break
    return hits


def extract_document_facts(
    record,
    containers,
    document,
    extracted_at,
):
    opportunity_id = str(
        record.get("opportunity_id")
        or record.get("opportunity_number")
        or "unknown"
    )
    facts = extract_deadlines(
        opportunity_id,
        containers,
        document,
        extracted_at,
    )

    award = extract_award_range(
        opportunity_id,
        containers,
        document,
        extracted_at,
    )
    if award:
        facts.append(award)

    expected_awards = first_pattern_fact(
        opportunity_id,
        containers,
        document,
        extracted_at,
        pattern=EXPECTED_AWARDS_RE,
        fact_type="expected_awards",
        label="Expected number of awards",
        value_builder=lambda match: int(match.group(1)),
        display_builder=lambda value: str(value),
    )
    if expected_awards:
        facts.append(expected_awards)

    duration = first_pattern_fact(
        opportunity_id,
        containers,
        document,
        extracted_at,
        pattern=DURATION_RE,
        fact_type="project_duration",
        label="Project duration",
        value_builder=lambda match: {
            "amount": int(match.group(1)),
            "unit": match.group(2).casefold(),
        },
        display_builder=lambda value: (
            f"{value['amount']} {value['unit']}"
        ),
    )
    if duration:
        facts.append(duration)

    page_limit = first_pattern_fact(
        opportunity_id,
        containers,
        document,
        extracted_at,
        pattern=PAGE_LIMIT_RE,
        fact_type="page_limit",
        label="Application page limit",
        value_builder=lambda match: int(
            next(group for group in match.groups() if group)
        ),
        display_builder=lambda value: f"{value} pages",
    )
    if page_limit:
        facts.append(page_limit)

    cost_share = extract_cost_share(
        opportunity_id,
        containers,
        document,
        extracted_at,
    )
    if cost_share:
        facts.append(cost_share)

    eligibility = extract_heading_excerpt(
        opportunity_id,
        containers,
        document,
        extracted_at,
        fact_type="eligibility_excerpt",
        label="Eligibility evidence",
        heading_pattern=re.compile(
            r"\b(?:eligible\s+applicants?|eligibility)\b",
            re.I,
        ),
    )
    if eligibility:
        facts.append(eligibility)

    review_criteria = extract_heading_excerpt(
        opportunity_id,
        containers,
        document,
        extracted_at,
        fact_type="review_criteria",
        label="Review criteria",
        heading_pattern=re.compile(
            r"\b(?:merit\s+review|review\s+criteria|selection\s+criteria)\b",
            re.I,
        ),
    )
    if review_criteria:
        facts.append(review_criteria)

    component_patterns = list(APPLICATION_COMPONENTS.items())
    facts.extend(
        extract_repeated_signals(
            opportunity_id,
            containers,
            document,
            extracted_at,
            patterns=component_patterns,
            fact_type="application_component",
            maximum=8,
        )
    )

    limited_patterns = [
        ("Potential institutional submission limit", LIMITED_SUBMISSION_RE)
    ]
    facts.extend(
        extract_repeated_signals(
            opportunity_id,
            containers,
            document,
            extracted_at,
            patterns=limited_patterns,
            fact_type="limited_submission",
            maximum=1,
        )
    )

    status_patterns = [
        (label, pattern)
        for _, label, pattern in STATUS_SIGNAL_PATTERNS
    ]
    status_facts = extract_repeated_signals(
        opportunity_id,
        containers,
        document,
        extracted_at,
        patterns=status_patterns,
        fact_type="status_signal",
        maximum=4,
    )
    for fact in status_facts:
        for status, label, _ in STATUS_SIGNAL_PATTERNS:
            if fact["label"] == label:
                fact["status_signal"] = status
                break
    facts.extend(status_facts)

    unique = {}
    for fact in facts:
        unique.setdefault(fact["id"], fact)
    return list(unique.values())[:MAX_FACTS]


def build_review_queue(record, facts, changed_since_previous, extraction):
    queue = []
    for fact in facts:
        if fact["type"] == "limited_submission":
            queue.append(
                {
                    "type": "limited_submission",
                    "label": "Verify the institutional submission limit",
                    "status": "needs_review",
                    "evidence_ids": [fact["id"]],
                }
            )
        elif (
            fact["type"] == "status_signal"
            and fact.get("status_signal") in {"cancelled", "superseded"}
        ):
            queue.append(
                {
                    "type": "status",
                    "label": "Verify whether this opportunity is still current",
                    "status": "needs_review",
                    "evidence_ids": [fact["id"]],
                }
            )

    structured_deadline = record.get("close_date")
    conflicting_deadline_ids = [
        fact["id"]
        for fact in facts
        if fact["type"] == "deadline"
        and fact.get("deadline_kind") == "application"
        and structured_deadline
        and fact.get("date") != structured_deadline
    ]
    if conflicting_deadline_ids:
        queue.append(
            {
                "type": "deadline_conflict",
                "label": "Reconcile the structured and notice application dates",
                "status": "needs_review",
                "evidence_ids": conflicting_deadline_ids[:4],
            }
        )

    if changed_since_previous:
        queue.append(
            {
                "type": "amendment",
                "label": "The official document changed; verify decisive facts",
                "status": "needs_review",
                "evidence_ids": [
                    fact["id"]
                    for fact in facts
                    if fact["type"] in {
                        "deadline",
                        "award_range",
                        "status_signal",
                    }
                ][:6],
            }
        )

    if extraction.get("text_characters", 0) < 300:
        queue.append(
            {
                "type": "document_unreadable",
                "label": "Very little selectable notice text was available",
                "status": "needs_review",
                "evidence_ids": [],
            }
        )
    return queue


def source_for_record(record):
    if record.get("primary_document_url"):
        return {
            "url": record["primary_document_url"],
            "name": record.get("primary_document_name"),
            "kind": "primary_notice",
        }
    agency_url = record.get("funding_opportunity_url")
    needs_gap_fill = (
        not record.get("close_date")
        or not (record.get("award_floor") or record.get("award_ceiling"))
        or record.get("status_verification_required")
        or record.get("has_preliminary_stage")
        or record.get("limited_submission")
    )
    if agency_url and needs_gap_fill:
        return {
            "url": agency_url,
            "name": None,
            "kind": "agency_notice",
        }
    return None


def source_signature(record, source):
    values = (
        source.get("url") if source else None,
        source.get("name") if source else None,
        record.get("api_revision"),
        record.get("api_version"),
        record.get("api_last_updated"),
        record.get("last_updated"),
    )
    return "|".join(str(value or "") for value in values)


def validate_public_url(value, resolver=socket.getaddrinfo):
    parsed = urlparse(str(value or "").strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise RuntimeError("Official document URL is not a valid HTTP(S) URL.")
    try:
        addresses = resolver(parsed.hostname, parsed.port or 443)
    except OSError as exc:
        raise RuntimeError(
            f"Could not resolve official-document host {parsed.hostname}."
        ) from exc
    for address in addresses:
        raw = address[4][0]
        ip = ipaddress.ip_address(raw)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise RuntimeError("Official document URL resolved to a non-public address.")
    return parsed.geturl()


def download_document(
    url,
    headers=None,
    *,
    timeout=30,
    maximum_bytes=MAX_DOWNLOAD_BYTES,
    session=requests,
):
    current_url = url
    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/pdf,text/html,text/plain;q=0.8,*/*;q=0.5",
        **(headers or {}),
    }
    for _ in range(6):
        validate_public_url(current_url)
        response = session.get(
            current_url,
            headers=request_headers,
            timeout=timeout,
            stream=True,
            allow_redirects=False,
        )
        if response.status_code in {301, 302, 303, 307, 308}:
            next_url = urljoin(current_url, response.headers.get("Location", ""))
            response.close()
            if not next_url:
                raise RuntimeError("Official document redirect was missing a location.")
            current_url = next_url
            continue
        if response.status_code == 304:
            response.close()
            return {
                "status_code": 304,
                "content": b"",
                "url": current_url,
                "content_type": response.headers.get("Content-Type"),
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"),
            }
        response.raise_for_status()
        declared_size = int(response.headers.get("Content-Length") or 0)
        if declared_size > maximum_bytes:
            response.close()
            raise RuntimeError(
                f"Official document exceeds the {maximum_bytes // 1_048_576} MB limit."
            )
        chunks = []
        size = 0
        for chunk in response.iter_content(chunk_size=65_536):
            if not chunk:
                continue
            size += len(chunk)
            if size > maximum_bytes:
                response.close()
                raise RuntimeError(
                    f"Official document exceeds the {maximum_bytes // 1_048_576} MB limit."
                )
            chunks.append(chunk)
        result = {
            "status_code": response.status_code,
            "content": b"".join(chunks),
            "url": current_url,
            "content_type": response.headers.get("Content-Type"),
            "etag": response.headers.get("ETag"),
            "last_modified": response.headers.get("Last-Modified"),
        }
        response.close()
        return result
    raise RuntimeError("Official document redirected too many times.")


def needs_subtopics(entry, enabled):
    """Whether a cached entry needs backfill segmentation (§8.3 insertion 3).

    Function-local import for the same reason as subtopic_fields: with the flag
    off nothing under scripts.subtopic_* is ever imported. Returns False
    immediately when disabled, so the hot path in the candidate loop costs one
    boolean check per document.
    """
    if not enabled:
        return False
    from scripts import subtopic_records, subtopic_segmentation

    return subtopic_records.needs_subtopic_extraction(
        entry,
        enabled=True,
        extractor_version=subtopic_segmentation.extractor_version(),
    )


def subtopic_fields(record, content, containers, document, fetched_at, enabled):
    """Segmentation result for one document, or ``{}`` when the flag is off.

    Returns a dict so the caller can splat it into the entry literal. With the
    flag off nothing is added at all -- not even ``"subtopics": []`` -- because
    the entry is serialized into data/document_evidence.json and an added empty
    key on hundreds of entries is not byte-identical (§0.5, §8.3 insertion 2).

    The import is function-local so that with the flag off `subtopic_*` is never
    imported, `pdfplumber` is never loaded, and a broken new module cannot break
    the nightly build by import error alone.

    Zero subtopics is a normal outcome and never raises: the except is broad on
    purpose, because a parsing failure here must not cost the parent record its
    facts (§9.3).
    """
    if not enabled:
        return {}
    from scripts import subtopic_records, subtopic_segmentation, subtopic_sources
    from scripts.pull_grants import collect_attachments, fetch_detail

    version = subtopic_segmentation.extractor_version()
    try:
        # §6.6 multi-attachment. The primary is tried first from bytes already
        # in hand, so a record whose topics are in the primary costs no extra
        # fetch. source_for_record() is untouched: this path is parallel and
        # subtopic-only, so fact extraction still reads exactly one document.
        result, chosen, attempts = subtopic_sources.best_segmentation(
            record,
            content,
            document,
            extract_containers=extract_containers,
            download=download_document,
            detail_fetcher=fetch_detail,
            collector=collect_attachments,
            parent_deadline=record.get("close_date"),
        )
        built = subtopic_records.build_records(
            record, result, document=chosen or document, as_of=fetched_at[:10]
        )
    except Exception as exc:  # noqa: BLE001 - never break the parent record
        return {
            "subtopics": [],
            "subtopic_reason": f"error_{type(exc).__name__}",
            "subtopic_extractor_version": version,
        }
    fields = {
        "subtopics": built,
        "subtopic_method": result.method,
        "subtopic_extractor_version": version,
        "subtopic_attempts": attempts.get("attempts", ()),
    }
    if chosen and (chosen.get("url") or None) != (document or {}).get("url"):
        # The topic list came from a secondary attachment, not the notice the
        # evidence cache records. Worth storing: it is the difference between
        # "this record has no topics" and "its topics are in another file".
        fields["subtopic_source_document"] = {
            "url": chosen.get("url"),
            "name": chosen.get("name"),
            "sha256": chosen.get("sha256"),
        }
    if result.reason:
        fields["subtopic_reason"] = result.reason
    return fields


def build_document_entry(
    record,
    source,
    response,
    previous,
    now,
    *,
    enable_subtopics=False,
    backfill_subtopics=False,
):
    fetched_at = iso_utc(now)
    content = response["content"]
    digest = hashlib.sha256(content).hexdigest()
    previous_document = (previous or {}).get("document") or {}
    previous_hash = previous_document.get("sha256")
    changed_since_previous = bool(previous_hash and previous_hash != digest)

    if previous_hash == digest and previous:
        entry = deepcopy(previous)
        entry["source_signature"] = source_signature(record, source)
        entry["checked_at"] = fetched_at
        entry["last_error"] = None
        entry["document"]["last_seen_at"] = fetched_at
        entry["document"]["etag"] = response.get("etag") or entry[
            "document"
        ].get("etag")
        entry["document"]["last_modified"] = (
            response.get("last_modified")
            or entry["document"].get("last_modified")
        )
        # §8.3 insertion 3, gate 3. The bytes are in hand -- downloaded and
        # hashed -- so segmenting here is free. Deliberately NOT falling
        # through to the full-extraction path: that would re-run fact
        # extraction and rewrite facts, review_queue and version, churning the
        # cache for no reason.
        if enable_subtopics and backfill_subtopics:
            containers, _extraction = extract_containers(
                content,
                response.get("content_type"),
                source.get("name"),
                entry["document"].get("url") or source["url"],
            )
            entry.update(
                subtopic_fields(
                    record,
                    content,
                    containers,
                    entry["document"],
                    fetched_at,
                    True,
                )
            )
        return entry, False

    version_history = deepcopy((previous or {}).get("version_history") or [])
    if previous_document.get("sha256"):
        version_history.append(
            {
                "sha256": previous_document.get("sha256"),
                "url": previous_document.get("url"),
                "name": previous_document.get("name"),
                "first_seen_at": previous_document.get("first_seen_at"),
                "last_seen_at": previous_document.get("last_seen_at"),
                "version": previous_document.get("version"),
            }
        )
        version_history = version_history[-MAX_VERSION_HISTORY:]
    version = int(previous_document.get("version") or 0) + 1
    document = {
        "url": response.get("url") or source["url"],
        "name": source.get("name"),
        "source_kind": source["kind"],
        "content_type": response.get("content_type"),
        "sha256": digest,
        "bytes": len(content),
        "etag": response.get("etag"),
        "last_modified": response.get("last_modified"),
        "version": version,
        "first_seen_at": fetched_at,
        "last_seen_at": fetched_at,
        "changed_since_previous": changed_since_previous,
    }
    containers, extraction = extract_containers(
        content,
        response.get("content_type"),
        source.get("name"),
        document["url"],
    )
    facts = extract_document_facts(
        record,
        containers,
        document,
        fetched_at,
    )
    program_area_hits = extract_program_areas(
        containers,
        document,
        fetched_at,
    )
    review_queue = build_review_queue(
        record,
        facts,
        changed_since_previous,
        extraction,
    )
    return {
        "source_signature": source_signature(record, source),
        "checked_at": fetched_at,
        "status": "current",
        "last_error": None,
        "document": document,
        "extraction": extraction,
        "facts": facts,
        "program_areas": program_area_hits,
        "review_queue": review_queue,
        "version_history": version_history,
        "archived_from_catalog_at": None,
        **subtopic_fields(
            record, content, containers, document, fetched_at, enable_subtopics
        ),
    }, True


def subtopic_only_candidates(records, *, enabled):
    """Catalog records the administrative path never fetches (§18.1 Cov1).

    Measured: `source_for_record()` declines **685 of 1,475 records**, and 672
    of them have no evidence entry at all, so no pattern can reach them because
    no bytes ever arrive (docs/COVERAGE_SURVEY.md stage 3).

    Returns ``[]`` when the flag is off, so the flag-off candidate set -- and
    therefore every flag-off artifact -- is untouched (§0.5).
    """
    if not enabled:
        return []
    candidates = []
    for record in records:
        opportunity_id = str(
            record.get("opportunity_id")
            or record.get("opportunity_number")
            or ""
        )
        if not opportunity_id or source_for_record(record):
            continue
        candidates.append((opportunity_id, record))
    return candidates


def refresh_subtopics_without_source(
    records,
    *,
    max_documents,
    fetcher,
    now,
    request_delay=0.0,
    enabled=False,
):
    """Segment the records `source_for_record()` declines. Subtopics only.

    **Never writes a `records` entry**, and that is the whole design. These
    documents were not vetted as the official notice -- `select_primary_document`
    declined them on purpose -- so giving them an evidence entry would attach
    `document_evidence` to the parent and publish exactly the wrong one-click
    link that rule exists to prevent. Results go to a separate store the caller
    puts under its own cache key, which exists only with the flag on.

    Returns ``(store, metrics)``. Never raises: zero subtopics is normal (§9.3).
    """
    store, metrics = {}, {
        "attempted": 0,
        "with_subtopics": 0,
        "remaining": 0,
        "agency_url_tried": 0,
    }
    if not enabled:
        return store, metrics
    from scripts import subtopic_sources

    candidates = subtopic_only_candidates(records, enabled=True)
    metrics["remaining"] = max(
        0, len(candidates) - min(len(candidates), max_documents)
    )
    fetched_at = iso_utc(now)
    for opportunity_id, record in candidates[:max_documents]:
        content, document = None, None
        source = subtopic_sources.subtopic_only_primary(record)
        if source:
            metrics["agency_url_tried"] += 1
            try:
                response = fetcher(source["url"], {})
                content = response.get("content")
                document = {
                    "url": response.get("url") or source["url"],
                    "name": source.get("name"),
                    "content_type": response.get("content_type"),
                    "sha256": (
                        hashlib.sha256(content).hexdigest() if content else None
                    ),
                    "source_kind": source["kind"],
                }
            except Exception:  # noqa: BLE001 - an agency page is optional here
                content, document = None, None
        fields = subtopic_fields(record, content, None, document, fetched_at, True)
        if not fields:
            continue
        metrics["attempted"] += 1
        if fields.get("subtopics"):
            metrics["with_subtopics"] += 1
        store[opportunity_id] = fields
        if request_delay:
            time.sleep(request_delay)
    return store, metrics


def due_for_check(entry, signature, now, recheck_days, *, needs_subtopics=False):
    if not entry:
        return True
    # §8.3 insertion 3, gate 1. On a steady-state night nearly every document
    # takes one of §4's three skip gates, so without this the ~1,400 already
    # cached documents are never even candidates and never get subtopics.
    if needs_subtopics:
        return True
    if entry.get("source_signature") != signature:
        return True
    checked_at = entry.get("checked_at")
    if not checked_at:
        return True
    try:
        checked = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    retry_days = (
        1
        if entry.get("status") == "failed" or entry.get("last_error")
        else recheck_days
    )
    return checked <= now - timedelta(days=retry_days)


def citation_deadline(fact):
    return {
        "kind": fact.get("deadline_kind") or "application",
        "date": fact.get("date"),
        "time": fact.get("time"),
        "timezone": fact.get("timezone"),
        "note": fact["citation"].get("quote"),
        "estimated": False,
        "source": "Official notice (machine extracted)",
        "source_url": fact["citation"].get("document_url"),
        "confidence": fact.get("confidence"),
        "evidence_id": fact["id"],
        "citation": fact["citation"],
        "required": fact.get("required"),
    }


def merge_document_entry(record, entry):
    output = deepcopy(record)
    if not entry:
        output["document_evidence_status"] = "pending"
        output["document_evidence"] = None
        output["document_search_text"] = None
        return output
    if entry.get("status") != "current":
        output["document_evidence_status"] = entry.get("status") or "failed"
        output["document_evidence"] = None
        output["document_search_text"] = None
        return output

    facts = deepcopy(entry.get("facts") or [])
    output["document_evidence_status"] = "current"
    output["document_evidence_checked_at"] = entry.get("checked_at")
    output["document_evidence"] = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "document": {
            key: value
            for key, value in (entry.get("document") or {}).items()
            if key
            in {
                "url",
                "name",
                "source_kind",
                "content_type",
                "sha256",
                "version",
                "first_seen_at",
                "last_seen_at",
                "changed_since_previous",
            }
        },
        "extraction": entry.get("extraction") or {},
        "facts": facts,
        "review_queue": deepcopy(entry.get("review_queue") or []),
    }

    deadlines = deepcopy(output.get("deadlines") or [])
    for fact in facts:
        if fact.get("type") != "deadline":
            continue
        duplicate = next(
            (
                deadline
                for deadline in deadlines
                if deadline.get("date") == fact.get("date")
                and deadline.get("kind")
                in {
                    fact.get("deadline_kind"),
                    "application"
                    if fact.get("deadline_kind") == "application"
                    else None,
                }
            ),
            None,
        )
        if duplicate:
            duplicate["document_evidence_id"] = fact["id"]
            duplicate["citation"] = fact["citation"]
            duplicate["document_confidence"] = fact["confidence"]
        else:
            deadlines.append(citation_deadline(fact))
    output["deadlines"] = deadlines

    preliminary = [
        fact
        for fact in facts
        if fact.get("type") == "deadline"
        and fact.get("deadline_kind")
        in {
            "letter_of_intent",
            "concept_paper",
            "white_paper",
            "preapplication",
            "preproposal",
        }
    ]
    if preliminary:
        output["has_preliminary_stage"] = True
        output["preliminary_stage_type"] = preliminary[0].get("deadline_kind")

    limited = next(
        (
            fact
            for fact in facts
            if fact.get("type") == "limited_submission"
        ),
        None,
    )
    if limited:
        output["limited_submission"] = True
        output["limited_submission_review"] = {
            "status": "needs_review",
            "evidence_id": limited["id"],
            "citation": limited["citation"],
        }

    status_signals = [
        fact.get("status_signal")
        for fact in facts
        if fact.get("type") == "status_signal"
        and fact.get("status_signal")
    ]
    output["document_status_signals"] = status_signals
    if any(value in {"cancelled", "superseded"} for value in status_signals):
        output["status_verification_required"] = True
        output["actionability_status"] = "document_status_needs_review"

    searchable = []
    for fact in facts:
        searchable.extend(
            [
                fact.get("label"),
                fact.get("display_value"),
                fact.get("citation", {}).get("quote"),
            ]
        )

    # Evidence-backed program-area discoverability: controlled terms that were
    # actually found in the official notice (see extract_program_areas). Add the
    # compact canonical labels to the indexed search text and their Topic tags
    # to the facet -- but NOT the raw quotes, so the browser catalog stays lean.
    # Full page/section citations remain in the evidence cache for auditability.
    # Revalidate cached hits against the current controlled vocabulary. This
    # lets a tightened recognizer remove an older false positive (for example,
    # "catalytic capital") without retaining stale search/facet pollution.
    patterns_by_label = {
        label: pattern for label, _, pattern in program_areas.ENTRIES
    }
    program_area_hits = [
        hit
        for hit in (entry.get("program_areas") or [])
        if patterns_by_label.get(hit.get("label"))
        and patterns_by_label[hit["label"]].search(
            ((hit.get("citation") or {}).get("quote") or "")
        )
    ]
    program_labels = [hit.get("label") for hit in program_area_hits if hit.get("label")]
    if program_labels:
        searchable.extend(program_labels)
        output["document_program_areas"] = program_labels
        inferred_topics = []
        for hit in program_area_hits:
            for topic in hit.get("topics") or []:
                if topic not in inferred_topics:
                    inferred_topics.append(topic)
        if inferred_topics:
            existing = list(output.get("topic_areas") or [])
            output["topic_areas"] = list(dict.fromkeys(existing + inferred_topics))

    output["document_search_text"] = clean_text(
        " ".join(str(value) for value in searchable if value)
    )
    return output


def document_metrics(records, cache, refreshed, not_modified, failures):
    current = [
        record
        for record in records
        if record.get("document_evidence_status") == "current"
    ]
    facts = [
        fact
        for record in current
        for fact in (
            (record.get("document_evidence") or {}).get("facts") or []
        )
    ]
    return {
        "document_current_count": len(current),
        "document_pending_count": sum(
            record.get("document_evidence_status") == "pending"
            for record in records
        ),
        "document_failed_count": sum(
            record.get("document_evidence_status") == "failed"
            for record in records
        ),
        "citation_fact_count": len(facts),
        "document_deadline_count": sum(
            fact.get("type") == "deadline" for fact in facts
        ),
        "limited_submission_review_count": sum(
            fact.get("type") == "limited_submission" for fact in facts
        ),
        "review_queue_count": sum(
            len((record.get("document_evidence") or {}).get("review_queue") or [])
            for record in current
        ),
        "changed_document_count": sum(
            bool(
                (record.get("document_evidence") or {})
                .get("document", {})
                .get("changed_since_previous")
            )
            for record in current
        ),
        "archived_cache_count": sum(
            bool(entry.get("archived_from_catalog_at"))
            for entry in cache.get("records", {}).values()
        ),
        "refreshed_count": refreshed,
        "not_modified_count": not_modified,
        "failed_request_count": len(failures),
        "failures": failures[:20],
    }


def subtopic_metrics(cached_records):
    """Subtopic counts and a rejection histogram (§8.3 insertion 4).

    `no_layer_accepted` is reported separately from genuine failures, and
    `run_budget` separately from `time_budget`, because conflating them hides
    the difference between "this corpus has no enumerated lists" and "the
    pattern set needs work" (§6.1, §18.1 package D).
    """
    reasons, methods, confidences = {}, {}, {}
    attempted = subtopic_count = 0
    for entry in cached_records.values():
        if "subtopics" not in entry:
            continue
        attempted += 1
        subtopics = entry.get("subtopics") or []
        subtopic_count += len(subtopics)
        reason = entry.get("subtopic_reason")
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1
        method = entry.get("subtopic_method")
        if method:
            methods[method] = methods.get(method, 0) + 1
        for record in subtopics:
            level = record.get("confidence")
            if level:
                confidences[level] = confidences.get(level, 0) + 1
    return {
        "documents_attempted": attempted,
        "documents_with_subtopics": sum(
            1
            for entry in cached_records.values()
            if entry.get("subtopics")
        ),
        "subtopic_record_count": subtopic_count,
        "rejection_reasons": dict(sorted(reasons.items())),
        "methods": dict(sorted(methods.items())),
        "confidence_counts": dict(sorted(confidences.items())),
    }


def validate_refresh_health(metrics, minimum_attempts=5, maximum_failure_rate=0.8):
    attempted = (
        int(metrics.get("refreshed_count") or 0)
        + int(metrics.get("not_modified_count") or 0)
        + int(metrics.get("failed_request_count") or 0)
    )
    if attempted < minimum_attempts:
        return
    failure_rate = int(metrics.get("failed_request_count") or 0) / attempted
    if failure_rate > maximum_failure_rate:
        raise RuntimeError(
            "Official-document refresh failed its health check: "
            f"{failure_rate:.0%} of {attempted} attempted sources failed."
        )


def enrich_document_evidence(
    catalog,
    cache,
    *,
    max_documents=45,
    request_delay=0.2,
    recheck_days=14,
    fetcher=download_document,
    now=None,
    enable_subtopics=False,
):
    now = now or utc_now()
    cached_records = cache.setdefault("records", {})
    records = catalog["opportunities"]
    current_ids = {
        str(record.get("opportunity_id") or record.get("opportunity_number"))
        for record in records
    }
    for opportunity_id, entry in cached_records.items():
        if opportunity_id not in current_ids:
            entry.setdefault("archived_from_catalog_at", iso_utc(now))
        else:
            entry["archived_from_catalog_at"] = None

    candidates = []
    for record in records:
        opportunity_id = str(
            record.get("opportunity_id")
            or record.get("opportunity_number")
            or ""
        )
        source = source_for_record(record)
        if not opportunity_id or not source:
            continue
        signature = source_signature(record, source)
        entry = cached_records.get(opportunity_id)
        source_recheck_days = (
            recheck_days
            if source["kind"] == "primary_notice"
            else max(30, recheck_days)
        )
        backfill = needs_subtopics(entry, enable_subtopics)
        if due_for_check(
            entry, signature, now, source_recheck_days, needs_subtopics=backfill
        ):
            candidates.append((record, source, signature, entry, backfill))
    candidates.sort(
        key=lambda item: (
            0
            if item[3]
            and item[3].get("source_signature") != item[2]
            else 1
            if not item[3]
            else 2
            if item[3].get("status") == "failed"
            else 3,
            0 if item[1]["kind"] == "primary_notice" else 1,
            0
            if (
                item[0].get("has_preliminary_stage")
                or item[0].get("limited_submission")
                or item[0].get("status_verification_required")
            )
            else 1,
            0
            if not (
                item[0].get("award_floor")
                or item[0].get("award_ceiling")
            )
            else 1,
            item[0].get("close_date") or "9999-12-31",
        )
    )

    refreshed = 0
    not_modified = 0
    failures = []
    for record, source, signature, previous, backfill in candidates[:max_documents]:
        opportunity_id = str(
            record.get("opportunity_id")
            or record.get("opportunity_number")
        )
        headers = {}
        previous_document = (previous or {}).get("document") or {}
        # §8.3 insertion 3, gate 2. A 304 returns no body, and you cannot
        # segment bytes you did not receive -- so a document needing backfill
        # asks for the whole thing.
        if previous and not backfill and previous_document.get("url") == source["url"]:
            if previous_document.get("etag"):
                headers["If-None-Match"] = previous_document["etag"]
            if previous_document.get("last_modified"):
                headers["If-Modified-Since"] = previous_document[
                    "last_modified"
                ]
        try:
            response = fetcher(source["url"], headers)
            if response.get("status_code") == 304 and previous:
                previous["checked_at"] = iso_utc(now)
                previous["last_error"] = None
                previous["source_signature"] = signature
                previous_document["last_seen_at"] = iso_utc(now)
                not_modified += 1
            else:
                entry, extracted = build_document_entry(
                    record,
                    source,
                    response,
                    previous,
                    now,
                    enable_subtopics=enable_subtopics,
                    backfill_subtopics=backfill,
                )
                cached_records[opportunity_id] = entry
                refreshed += int(extracted)
                not_modified += int(not extracted)
        except Exception as exc:  # noqa: BLE001 - retain other records
            failure = {
                "opportunity_id": opportunity_id,
                "url": source["url"],
                "error": str(exc)[:300],
            }
            failures.append(failure)
            if previous and previous.get("status") == "current":
                previous["checked_at"] = iso_utc(now)
                previous["last_error"] = failure["error"]
            else:
                cached_records[opportunity_id] = {
                    "source_signature": signature,
                    "checked_at": iso_utc(now),
                    "status": "failed",
                    "last_error": failure["error"],
                    "document": {
                        "url": source["url"],
                        "name": source.get("name"),
                        "source_kind": source["kind"],
                    },
                    "facts": [],
                    "review_queue": [],
                    "version_history": deepcopy(
                        (previous or {}).get("version_history") or []
                    ),
                    "archived_from_catalog_at": None,
                }
        if request_delay:
            time.sleep(request_delay)

    merged = []
    for record in records:
        opportunity_id = str(
            record.get("opportunity_id")
            or record.get("opportunity_number")
            or ""
        )
        merged.append(
            merge_document_entry(record, cached_records.get(opportunity_id))
        )
    output = deepcopy(catalog)
    output["opportunities"] = merged
    output["search_index"] = build_search_index(merged)
    output["document_evidence_generated_at"] = iso_utc(now)
    output.setdefault("source", {})["document_evidence"] = {
        "method": (
            "Official PDF/HTML retrieval with deterministic extraction and "
            "page/section citations"
        ),
        "raw_documents_retained": False,
        "schema_version": EVIDENCE_SCHEMA_VERSION,
    }
    metrics = document_metrics(
        merged,
        cache,
        refreshed,
        not_modified,
        failures,
    )
    metrics["remaining_update_count"] = max(
        0,
        len(candidates) - min(len(candidates), max_documents),
    )
    if enable_subtopics:
        # §8.3 insertion 4. Only present with the flag on, so the diagnostics
        # block is byte-identical when it is off.
        metrics["subtopics"] = subtopic_metrics(cached_records)
        # §18.1 Cov1. Runs after the administrative pass and writes nowhere
        # near it: a separate store, a separate cache key, no record entry.
        subtopic_only, subtopic_only_metrics = refresh_subtopics_without_source(
            records,
            max_documents=max_documents,
            fetcher=fetcher,
            now=now,
            request_delay=request_delay,
            enabled=True,
        )
        if subtopic_only:
            cache["subtopic_only"] = subtopic_only
        metrics["subtopics"]["subtopic_only"] = subtopic_only_metrics
    output.setdefault("diagnostics", {})["document_evidence"] = metrics
    cache["generated_at"] = iso_utc(now)
    return output, cache


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Extract citation-backed facts from official notices."
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_CATALOG,
        help="Generated catalog JavaScript asset.",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=DEFAULT_CACHE,
        help="Compact document-evidence cache.",
    )
    parser.add_argument(
        "--max-documents",
        type=int,
        default=45,
        help="Maximum new or due official sources to retrieve (default: 45).",
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=0.2,
        help="Seconds between document requests (default: 0.2).",
    )
    parser.add_argument(
        "--recheck-days",
        type=int,
        default=14,
        help="Recheck unchanged source URLs after this many days (default: 14).",
    )
    parser.add_argument(
        "--enable-subtopics",
        action="store_true",
        help=(
            "Segment official notices into child topic records. Off by "
            "default; only the Phase 4 step turns this on."
        ),
    )
    parser.add_argument(
        "--subtopic-cache",
        type=Path,
        default=DEFAULT_SUBTOPIC_CACHE,
        help="Subtopic record cache, written only with --enable-subtopics.",
    )
    args = parser.parse_args(argv)
    if args.max_documents < 0:
        parser.error("--max-documents must be non-negative")
    if args.request_delay < 0:
        parser.error("--request-delay must be non-negative")
    if args.recheck_days < 1:
        parser.error("--recheck-days must be at least one")
    return args


def main(argv=None):
    args = parse_args(argv)
    catalog = read_catalog(args.catalog)
    cache = read_cache(args.cache)
    enriched, cache = enrich_document_evidence(
        catalog,
        cache,
        max_documents=args.max_documents,
        request_delay=args.request_delay,
        recheck_days=args.recheck_days,
        enable_subtopics=args.enable_subtopics,
    )
    write_cache(cache, args.cache)
    if args.enable_subtopics:
        # Written only with the flag on, so the flag-off artifact set is
        # unchanged and §0.5 byte-identity holds by construction.
        from scripts import subtopic_records

        subtopic_cache = subtopic_records.empty_cache()
        sources = list((cache.get("records") or {}).items())
        # §18.1 Cov1 results carry no evidence entry by design, so they are a
        # second source for the same cache rather than a second cache.
        sources += list((cache.get("subtopic_only") or {}).items())
        for opportunity_id, entry in sources:
            if "subtopics" not in entry:
                continue
            subtopic_records.upsert_parent(
                subtopic_cache,
                opportunity_id,
                entry.get("subtopics") or [],
                as_of=iso_utc(utc_now())[:10],
                reason=entry.get("subtopic_reason"),
                method=entry.get("subtopic_method"),
            )
        subtopic_records.write_cache(subtopic_cache, args.subtopic_cache)
    write_catalog(enriched, args.catalog)
    metrics = enriched["diagnostics"]["document_evidence"]
    validate_refresh_health(metrics)
    print(
        "Document evidence current for "
        f"{metrics['document_current_count']:,}/"
        f"{enriched['record_count']:,} records; "
        f"{metrics['citation_fact_count']:,} cited facts; "
        f"{metrics['failed_request_count']:,} request failures; "
        f"{metrics['remaining_update_count']:,} queued."
    )


if __name__ == "__main__":
    main()
