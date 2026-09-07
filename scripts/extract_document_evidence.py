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
import os
from pathlib import Path
import re
import socket
import sys
import tempfile
import time
from urllib.parse import unquote, urljoin, urlparse

from pypdf import PdfReader
import requests

from scripts.build_catalog import (
    build_search_index,
    facet_counts,
    clean_text,
    iso_utc,
    write_catalog,
)
from scripts.enrich_catalog import read_catalog
from scripts import program_areas, notice_semantics, notice_schedule, notice_structure_cache


EVIDENCE_SCHEMA_VERSION = 1
EXTRACTOR_IDENTITY = "official-evidence-3"
DEADLINE_EXTRACTOR_IDENTITY = "submission-date-6"
FACT_CONTRACT_VERSION = "typed-notice-facts-1"
DEFAULT_CATALOG = Path("data/opportunities.js")
DEFAULT_CACHE = Path("data/document_evidence.json")
DEFAULT_SUBTOPIC_CACHE = Path("data/subtopics.js")
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
    r"(?<![\d:])\b((?:1[0-2]|0?[1-9])(?::[0-5]\d(?::[0-5]\d)?)?\s*(?:a\.?m\.?|p\.?m\.?))(?![A-Za-z])"
    r"(?:\s*\(noon\))?(?:\s+(?:U\.S\.\s+)?(Eastern|Central|Mountain|Pacific|Alaska|Hawaii(?:-Aleutian)?|Atlantic|UTC|GMT|CET|AK[SD]T|HST|[ECMPA][SD]?T)\b"
    r"(?:\s+(?:Time|Standard Time|Daylight(?: Savings)? Time))?)?",
    re.I,
)
DEADLINE_CUE_RE = re.compile(
    r"\b(?:deadlines?|due|submit(?:ted)?|submissions?|received|closing|will close|"
    r"no later than|must be filed|applications? by|proposals? by)\b",
    re.I,
)
DEADLINE_SUBMISSION_LABEL = (
    r"(?:(?:(?:full|final)\s+)?(?:applications?|proposals?)|"
    r"pre[\s-]?(?:applications?|proposals?)|preliminary\s+proposals?|"
    r"letters?\s+of\s+(?:intent|interest)|LOIs?|concept\s+papers?|white\s+papers?)"
)
DEADLINE_LABEL_RE = re.compile(
    rf"\b{DEADLINE_SUBMISSION_LABEL}\s+(?:submission\s+)?deadlines?\b|"
    rf"\b(?:submission\s+deadlines?|deadlines?\s+for(?:\s+{DEADLINE_SUBMISSION_LABEL})?)\b",
    re.I,
)
SUBMISSION_GROUP_VALUE = r"(?:[IVX]+|\d+|one|two|three|four|five|six|seven|eight|nine|ten)"
SUBMISSION_GROUP_PATTERN = rf"(?:(?:phase|round|cycle|year)\s+{SUBMISSION_GROUP_VALUE}|FY\s*\d{{2,4}})\b"
SUBMISSION_GROUP_PREFIX_RE = re.compile(rf"\b(?:{SUBMISSION_GROUP_PATTERN}\s*[-:–—,(\[]?\s*)+$", re.I)
SUBMISSION_GROUP_RE = re.compile(
    rf"\b(?:(?P<kind>phase|round|cycle|year)\s+(?P<value>{SUBMISSION_GROUP_VALUE})|FY\s*(?P<fy>\d{{2,4}}))\b", re.I)
DEADLINE_KINDS = (
    (
        "letter_of_intent",
        "Letter of intent deadline",
        re.compile(r"\b(?:letters?\s+of\s+(?:intent|interest)|LOIs?)\b", re.I),
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
    r"\$\s*(\d[\d,]*(?:\.\d+)?)"
    r"(?:\s*(thousand|million|billion|(?<=\d)[KMB]|(?-i:[KMB])(?!\.)))?\b",
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


def parse_now(value):
    """Parse an explicit clock override for deterministic offline builds."""
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "--now must be an ISO 8601 timestamp with a timezone"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError(
            "--now must be an ISO 8601 timestamp with a timezone"
        )
    return parsed.astimezone(timezone.utc)


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


def prune_cache_to_catalog(cache, catalog):
    """Remove evidence state whose stable parent is absent from the catalog.

    The catalog is the currentness authority. Keeping an ``archived`` evidence
    entry in the current cache made cache-derived denominators silently include
    departed opportunities (DEBT-4). This mutates ``cache`` and returns the
    sorted removed identifiers so a one-time campaign can preserve its frame.
    """
    current_ids = {
        str(record.get("opportunity_id") or record.get("opportunity_number") or "")
        for record in catalog.get("opportunities") or []
    }
    current_ids.discard("")
    removed = set()
    for key in ("records", "subtopic_only"):
        entries = cache.get(key)
        if not isinstance(entries, dict):
            continue
        stale = set(entries) - current_ids
        removed.update(stale)
        cache[key] = {
            identifier: entry
            for identifier, entry in entries.items()
            if identifier in current_ids
        }
    return sorted(removed)


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


# Shared source structure retains short fields and table ownership.
from scripts.notice_structure import NoticeHTMLParser, STRUCTURE_VERSION


def extract_pdf_pages(content):
    reader = PdfReader(io.BytesIO(content), strict=False)
    if reader.is_encrypted:
        try:
            if not reader.decrypt(""):
                raise RuntimeError("Official PDF is encrypted and cannot be read.")
        except Exception as error:
            raise RuntimeError("Official PDF is encrypted and cannot be read.") from error
    total_pages = len(reader.pages)
    pages = []
    unreadable, truncated_pages, layout_unavailable = [], [], []
    for index, page in enumerate(reader.pages, start=1):
        if index > MAX_PDF_PAGES:
            break
        try:
            raw_text = page.extract_text() or ""
            text = clean_document_text(raw_text)
        except Exception:  # noqa: BLE001 - retain other readable pages
            text = ""
        if not text:
            unreadable.append(index)
        if text:
            try:
                layout = "\n".join(line.rstrip() for line in (page.extract_text(extraction_mode="layout") or "").splitlines())
                if not layout:
                    layout_unavailable.append(index)
            except Exception:
                layout = ""
                layout_unavailable.append(index)
            if len(text) > MAX_PAGE_CHARS:
                truncated_pages.append(index)
            if len(layout) > MAX_PAGE_CHARS and index not in truncated_pages:
                truncated_pages.append(index)
            text = text[:MAX_PAGE_CHARS]
            layout = layout[:MAX_PAGE_CHARS]
            blocks = []
            for line in re.finditer(r"[^\n]+", text):
                blocks.append({"block_id": f"pdf-{index}-{len(blocks) + 1}", "kind": "line",
                    "text": line.group(), "span": line.span(), "reading_order": len(blocks),
                    "page": index})
            pages.append(
                {
                    "page": index,
                    "section": None,
                    "anchor": None,
                    "text": text,
                    "structure": blocks,
                    # Preserve physical column positions without guessing which
                    # column is a deadline, amount, or qualifier. Native readers
                    # must establish that from the actual source headers.
                    "layout_rows": [{"line": n + 1, "text": line,
                        "cells": [{"text": m.group().strip(), "column_start": m.start(), "column_end": m.end()}
                                  for m in re.finditer(r"\S(?:.*?\S)?(?=\s{2,}|$)", line)]}
                        for n, line in enumerate(layout.splitlines()) if line.strip()],
                    "truncated": index in truncated_pages,
                }
            )
    # Repeated running headings are evidence context, not substantive sections.
    edges = {}
    for container in pages:
        lines = container["structure"]
        for block in lines[:5] + lines[-2:]:
            key = re.sub(r"\d+", "#", block["text"].strip())
            if len(key) > 8:
                edges.setdefault(key, set()).add(container["page"])
    repeated = {text for text, seen in edges.items() if len(seen) >= max(3, len(pages) // 2)}
    for container in pages:
        container["toc"] = bool(re.search(r"^\s*(?:Table of Contents|Contents?)\s*$", container["text"][:1800], re.I | re.M))
        for block in container["structure"]:
            block["repeated_header"] = re.sub(r"\d+", "#", block["text"].strip()) in repeated
            block["toc"] = container["toc"]
    return pages, {
        "method": "pypdf",
        "page_count": total_pages,
        "pages_read": min(total_pages, MAX_PDF_PAGES),
        "pages_with_text": len(pages),
        "truncated": total_pages > MAX_PDF_PAGES or bool(truncated_pages),
        "truncated_pages": truncated_pages,
        "unreadable_pages": unreadable,
        "layout_unavailable_pages": layout_unavailable,
        "structure_version": STRUCTURE_VERSION,
    }


def extract_html_sections(content, *, nsf_submission_component=False):
    decoded = content.decode("utf-8", errors="replace")
    parser = NoticeHTMLParser(nsf_submission_component=nsf_submission_component)
    parser.feed(decoded)
    parser.close()
    if nsf_submission_component:
        leaves = {'program-due-dates__date-type', 'program-due-dates__desc', 'program-due-dates__due-by-time-text', 'program-due-dates__sub-type'}
        parser.blocks = [b for b in parser.blocks if b.get('source_component') != 'nsf_submission_fields'
                         or (parser.submission_components == 1 and any(
                             leaves.intersection(a.get('class', '').split()) for a in b.get('ancestors', [])))]
        if parser.submission_components > 1:
            parser.diagnostics.append('ambiguous_nsf_submission_component')
    grouped = []
    for block in parser.blocks:
        if (
            grouped
            and grouped[-1]["section"] == block["section"]
            and grouped[-1]["anchor"] == block["anchor"]
            and grouped[-1].get('source_component') == block.get('source_component')
            and len(grouped[-1]["text"]) + len(block["text"]) < MAX_PAGE_CHARS
        ):
            start = len(grouped[-1]["text"]) + 1
            grouped[-1]["text"] += f"\n{block['text']}"
            grouped[-1]["blocks"].append((start, len(grouped[-1]["text"])))
            grouped[-1]["structure"].append({**block, "span": (start, len(grouped[-1]["text"]))})
        else:
            grouped.append(
                {
                    "page": None,
                    "section": block["section"],
                    "anchor": block["anchor"],
                    **({'source_component': block['source_component']} if block.get('source_component') else {}),
                    "text": block["text"],
                    "blocks": [(0, len(block["text"]))],
                    "structure": [{**block, "span": (0, len(block["text"]))}],
                }
            )
    return grouped, {
        "method": "html",
        "page_count": None,
        "pages_read": None,
        "pages_with_text": len(grouped),
        "truncated": False,
        "structure_version": STRUCTURE_VERSION,
        "warnings": parser.diagnostics,
    }


def content_kind(content, content_type, name, final_url):
    media = str(content_type or "").split(";", 1)[0].strip().casefold()
    suffix_text = f"{name or ''} {final_url or ''}".casefold()
    if content[:5] == b"%PDF-":
        return "pdf"
    if re.search(
        br"^\s*<(?:!doctype\s+html|html)\b",
        content[:500],
        re.I,
    ):
        return "html"
    if media == "application/pdf":
        return "pdf"
    if media in {"text/html", "application/xhtml+xml"}:
        return "html"
    if ".pdf" in suffix_text and media in {"", "application/octet-stream"}:
        return "pdf"
    if media.startswith("text/"):
        return "text"
    return "unsupported"


def extract_containers(content, content_type, name, final_url):
    kind = content_kind(content, content_type, name, final_url)
    if kind == "pdf":
        containers, extraction = extract_pdf_pages(content)
    elif kind == "html":
        containers, extraction = extract_html_sections(scoped_html(content, final_url),
            nsf_submission_component=urlparse(final_url).hostname in {'www.nsf.gov', 'nsf.gov'})
    elif kind == "text":
        decoded = clean_document_text(content.decode("utf-8", errors="replace"))
        containers = [
            {
                "page": None,
                "section": "Official notice",
                "anchor": None,
                "text": decoded[:MAX_PAGE_CHARS],
            }
        ]
        extraction = {
            "method": "text",
            "page_count": None,
            "pages_read": None,
            "pages_with_text": int(bool(containers[0]["text"])),
            "truncated": len(decoded) > MAX_PAGE_CHARS,
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


def source_scope_identity(url):
    parsed = urlparse(str(url or ""))
    if parsed.hostname in {"simonsfoundation.org", "www.simonsfoundation.org"} and parsed.path.startswith("/grant/"):
        return "simons-grant-article-1"
    if parsed.hostname in {"arpa-e-foa.energy.gov", "eere-exchange.energy.gov", "netl-exchange.energy.gov"}:
        return "exchange-notice-group-2"
    return None


def scoped_html(content, url):
    """A supported notice owns one bounded element, never linked sibling calls."""
    parsed = urlparse(str(url or ""))
    article = source_scope_identity(url) == "simons-grant-article-1"
    if not article and parsed.hostname not in {"arpa-e-foa.energy.gov", "eere-exchange.energy.gov", "netl-exchange.energy.gov"}:
        return content
    target = unquote(parsed.fragment)
    if not article and not re.fullmatch(r"FoaId[0-9a-fA-F-]{36}", target, re.I):
        raise ValueError("Exchange evidence requires a bounded official notice fragment")

    class Fragment(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.depth, self.matches, self.parts = 0, 0, []
            self.root_tag = None

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            selected = (tag == "article" and "o-detail" in attrs.get("class", "").split()) if article else (
                tag in {"div", "section", "article"} and str(attrs.get("id", "")).casefold() == target.casefold())
            if selected:
                self.matches += 1
            if not self.depth:
                if not selected:
                    return
                self.root_tag = tag
                self.depth = 1
            elif tag == self.root_tag:
                # HTML permits omitted </li> and </p> tags. Only matching
                # container tags determine the selected notice's boundary.
                self.depth += 1
            if self.depth:
                self.parts.append(self.get_starttag_text())

        def handle_startendtag(self, tag, attrs):
            if self.depth:
                self.parts.append(self.get_starttag_text())

        def handle_endtag(self, tag):
            if self.depth:
                self.parts.append("</" + tag + ">")
                if tag == self.root_tag:
                    self.depth -= 1

        def handle_data(self, data):
            if self.depth:
                self.parts.append(data)

        def handle_entityref(self, name):
            self.handle_data("&" + name + ";")

        def handle_charref(self, name):
            self.handle_data("&#" + name + ";")

    fragment = Fragment()
    fragment.feed(content.decode("utf-8", errors="replace"))
    if not article and not fragment.matches:
        # The same official portal also nests a named FoaId anchor within one
        # .foaGroup. Own that complete group, never the summary grid or siblings.
        class ExchangeGroup(Fragment):
            def __init__(self):
                super().__init__()
                self.groups, self.owned = [], 0

            def handle_starttag(self, tag, attrs):
                attributes = dict(attrs)
                selected = tag == "div" and "foaGroup" in attributes.get("class", "").split()
                if not self.depth:
                    if not selected:
                        return
                    self.depth, self.parts, self.owned = 1, [], 0
                elif tag == "div":
                    self.depth += 1
                if tag == "a" and (attributes.get("name") or attributes.get("id") or "").casefold() == target.casefold():
                    self.owned += 1
                self.parts.append(self.get_starttag_text())

            def handle_endtag(self, tag):
                if self.depth:
                    self.parts.append("</" + tag + ">")
                    if tag == "div":
                        self.depth -= 1
                    if not self.depth and self.owned:
                        if self.owned != 1:
                            raise ValueError("official Exchange group has ambiguous ownership")
                        self.groups.append(list(self.parts))

        groups = ExchangeGroup()
        groups.feed(content.decode("utf-8", errors="replace"))
        if len(groups.groups) == 1 and not groups.depth:
            return "".join(groups.groups[0]).encode("utf-8")
    if fragment.matches != 1 or fragment.depth or not fragment.parts:
        raise ValueError("official notice does not expose one complete bounded article" if article
                         else "official Exchange notice does not expose one complete bounded fragment")
    return "".join(fragment.parts).encode("utf-8")


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
    owned = [block for block in container.get("structure", [])
             if block.get("span") and block["span"][0] <= start < block["span"][1]]
    structural_reference = None
    if len(owned) == 1:
        structural_reference = {key: owned[0][key] for key in
            ("block_id", "kind", "row", "table_id", "heading_path", "source_position") if key in owned[0]}
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
        **({"structural_reference": structural_reference} if structural_reference else {}),
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
        "fact_contract": FACT_CONTRACT_VERSION,
        "source_authority": "machine_extracted_official_document",
        "subject": {"deadline": "submission", "expected_awards": "program_awards",
                    "project_duration": "award_project"}.get(fact_type, fact_type),
        "parser_version": EXTRACTOR_IDENTITY,
        # Semantic extractors supply applicable subject/stage/basis/obligation;
        # absence means unknown, never an inferred negative or a source mandate.
    }
    fact.update(extra)
    return fact


def deadline_kind(context, date_offset=None):
    matches = []
    specific = [match.span() for kind, _, pattern in DEADLINE_KINDS if kind != "application"
                for match in pattern.finditer(context)]
    for kind, label, pattern in DEADLINE_KINDS:
        for match in pattern.finditer(context):
            if kind == "application" and any(left <= match.start() < right for left, right in specific):
                continue  # "Application" inside "Pre-Application" is not a full stage.
            distance = (
                abs(((match.start() + match.end()) // 2) - date_offset)
                if date_offset is not None
                else match.start()
            )
            matches.append((distance, match.start(), kind, label))
    if not matches:
        if re.search(r"\b(?:submissions?|closing\s+date|due\s+dates?|solution\s+summar(?:y|ies))\b|^deadline\b", context, re.I):
            return "application", "Full application deadline"
        return None
    _, _, kind, label = min(matches, key=lambda item: (item[0], item[1]))
    return kind, label


# Deliberately bounded field grammar. This is not a general English parser:
# unsupported lists, replacements and scope annotations lose narrative evidence.
_SUBMISSION_SUBJECT = rf"{DEADLINE_SUBMISSION_LABEL}(?:\s*\((?:LOI|Letter of Intent|Preproposal)\))?"
_DEADLINE_FIELD = re.compile(
    rf"\b(?:{_SUBMISSION_SUBJECT}\s+(?:submission\s+)?(?:deadlines?|due(?:\s+dates?)?)"
    rf"|(?:deadlines?|closing\s+date)\s+for\s+{_SUBMISSION_SUBJECT}(?:\s+submission)?"
    rf"|{_SUBMISSION_SUBJECT}\s+(?:(?:is\s+required\s+and\s+)?(?:must|shall)\s+be\s+(?:submitted|received|filed)|(?:are|is|will\s+be)\s+due)"
    rf"|(?:submissions?|solution\s+summar(?:y|ies))\s+(?:due|must\s+be\s+(?:submitted|received))"
    rf"|application\s+period\s+will\s+close|closing\s+date(?:\s+for\s+this\s+opportunity)?"
    rf"|(?P<generic>submission\s+deadlines?|deadline))\b", re.I)
_REQUIREMENT = re.compile(r"(?<!\w)(?:\(\s*(?:required|optional)\s*\)|\[\s*(?:required|optional)\s*\]|not\s+required|required|optional)(?!\w)", re.I)
_REPLACEMENT_LINK = r"(?:(?:has\s+been|was)\s+)?(?:extended|moved|changed|revised)\s+(?:to|until)\s+"
_VALUE_LINK = re.compile(
    r"[\s,:=–—\-()\[\]]*(?:(?:is|are|was)\s+)?"
    rf"(?:{_REPLACEMENT_LINK})?"
    r"(?:(?:on|by|at|of|due|no\s+later\s+than)\s*)*[\s,:=–—\-()\[\]]*", re.I)
_CLOCK_LINK = re.compile(
    r"[\s,:()\[\]]*(?:(?:at|by|due\s+(?:at|by))|"
    r"(?:(?:applications?|submissions?)\s+)?(?:must\s+be\s+received|are\s+due|closes?)\s+(?:at|by))?\s*", re.I)


def _balanced_deadline_field(text):
    stack = []
    for character in text:
        if character in '([':
            stack.append(character)
        elif character in ')]':
            if not stack or stack.pop() != {')': '(', ']': '['}[character]:
                return False
    return not stack


def _deadline_boundaries(text, start, end):
    for boundary in re.finditer(r'[;•|\n]|[.!?]\s+(?=[A-Z])', text[start:end]):
        position = start + boundary.start()
        if text[position] == '\n':
            following = position + 1 + len(text[position + 1:]) - len(text[position + 1:].lstrip())
            if TIME_RE.match(text, following) or DATE_RE.match(text, following):
                continue  # A source line wrap inside a field is not a new field.
        if not re.search(r'\b[ap]\.?m\.$', text[:position + 1], re.I):
            yield position, start + boundary.end()


def _clock_extent(text, clock):
    """Return the whole clock token and whether its redundant zone agrees."""
    noon = re.match(r'\s*\(noon\)', text[clock.end():], re.I)
    if noon:
        value = re.sub(r'[.\s]', '', clock.group(1)).casefold()
        return clock.end() + noon.end(), value in {'12pm', '12:00pm', '12:00:00pm'}
    alias = re.match(r'\s*\(([A-Z]{2,4})\)', text[clock.end():], re.I)
    if not alias:
        return clock.end(), True
    zone = (clock.group(2) or '').casefold()
    stems = {'eastern': 'E', 'central': 'C', 'mountain': 'M', 'pacific': 'P',
             'alaska': 'AK', 'atlantic': 'A', 'hawaii': 'H', 'hawaii-aleutian': 'H'}
    descriptor = re.search(r'\b(Standard|Daylight)(?:\s+Savings)?\s+Time\b', clock.group(0), re.I)
    expected = (stems[zone] + (descriptor.group(1)[0].upper() if descriptor else '') + 'T'
                if zone in stems else zone.upper())
    if zone == 'hawaii' and not descriptor:
        expected = 'HST'
    return clock.end() + alias.end(), alias.group(1).upper() == expected


def deadline_timezone(clock):
    if not clock or not clock.group(2):
        return None
    descriptor = re.search(r'\b(Standard|Daylight)(?:\s+Savings)?\s+Time\b', clock.group(0), re.I)
    stems = {'eastern': 'E', 'central': 'C', 'mountain': 'M', 'pacific': 'P',
             'alaska': 'AK', 'atlantic': 'A', 'hawaii': 'H', 'hawaii-aleutian': 'H'}
    zone = clock.group(2)
    if descriptor and zone.casefold() in stems:
        return stems[zone.casefold()] + descriptor.group(1)[0].upper() + 'T'
    return clean_text(zone)


def _without_clocks(text):
    parts, end = [], 0
    for clock in TIME_RE.finditer(text):
        parts.extend((text[end:clock.start()], ' '))
        end, _ = _clock_extent(text, clock)
    return ''.join(parts) + text[end:]


def explicit_deadline_requirement(context):
    values = {not bool(re.search(r'optional|not\s+required', match.group(0), re.I))
              for match in _REQUIREMENT.finditer(context)}
    if len(values) == 1:
        return values.pop()
    if not values and re.search(r'\b(?:must|shall)\b', context, re.I):
        return True
    return None


def deadline_context(container, match):
    """Prove one date's local field; never borrow another value or infer a list."""
    text = container['text']
    start, end = max(0, match.start() - 230), min(len(text), match.end() + 230)
    block_end = len(text)
    for left, right in container.get('blocks') or []:
        if left <= match.start() < right:
            start, end = max(start, left), min(end, right)
            block_end = right
            break
    fields = list(_DEADLINE_FIELD.finditer(text, start, end))
    boundaries = list(_deadline_boundaries(text, start, end))
    for index, field in enumerate(fields):
        field_start = field.start()
        qualifier = SUBMISSION_GROUP_PREFIX_RE.search(text[start:field_start])
        if qualifier:
            field_start = start + qualifier.start()
        left = max([start] + [after for _, after in boundaries if after <= field_start])
        next_start = fields[index + 1].start() if index + 1 < len(fields) else end
        next_qualifier = SUBMISSION_GROUP_PREFIX_RE.search(text[field.end():next_start])
        if next_qualifier:
            next_start = field.end() + next_qualifier.start()
        right = min([end] + [before for before, _ in boundaries if before >= field.end()]
                    + [next_start])
        if right == end and end < block_end:
            continue  # The bounded window cannot prove how this field ends.
        if field.group('generic') and text[left:field_start].strip(' \t:–—-'):
            continue  # E.g. an award/policy deadline cannot become an application.
        value_start = field.end()
        before = list(DATE_RE.finditer(text, left, field_start))
        previous = before[-1] if before else None
        gap = text[previous.end():field_start] if previous else ''
        postfix = bool(previous and re.fullmatch(r'[\s,]*(?:at\s+|by\s+)?', _without_clocks(gap.rstrip(' ([')), re.I)
                       and gap.rstrip().endswith(('(', '[')))
        if postfix:
            closing = ')' if gap.rstrip().endswith('(') else ']'
            close = re.match(r'\s*' + re.escape(closing), text[value_start:right])
            if not close:
                continue
            value_start += close.end()
            if DATE_RE.search(text, value_start, right):
                continue  # An old value plus a possible replacement is withheld.
            if match.start() != previous.start():
                continue
            value = text[previous.start():field_start].rstrip(' ([') + ' ' + text[value_start:right]
        else:
            if not value_start <= match.start() < right:
                continue
            if index == 0 and not re.fullmatch(r'\s*(?:(?:a|the)\s+)?', text[left:field_start], re.I):
                continue
            value = text[value_start:right]
        dates = list(DATE_RE.finditer(value))
        if len(dates) != 1 or not _balanced_deadline_field(value):
            continue
        date = dates[0]
        prefix = value[:date.start()]
        if not _VALUE_LINK.fullmatch(SUBMISSION_GROUP_RE.sub(' ', _REQUIREMENT.sub(' ', _without_clocks(prefix)))):
            continue
        header = text[field_start:field.end()] + ' ' + ' '.join(m.group(0) for m in SUBMISSION_GROUP_RE.finditer(prefix))
        groups = {}
        for group in SUBMISSION_GROUP_RE.finditer(header):
            groups.setdefault(group.group('kind') or 'fiscal_year', set()).add(
                (group.group('value') or group.group('fy')).casefold())
        if any(len(values) > 1 for values in groups.values()):
            continue
        markers = list(_REQUIREMENT.finditer(prefix))
        clocks = list(TIME_RE.finditer(value))
        owned_clock = None
        tail_start = date.end()
        if len(clocks) == 1:
            clock = clocks[0]
            clock_end, valid = _clock_extent(value, clock)
            gap = _REQUIREMENT.sub(' ', value[date.end():clock.start()])
            if valid and (clock.end() <= date.start() or _CLOCK_LINK.fullmatch(gap)):
                owned_clock = clock
                tail_start = max(tail_start, clock_end)
                markers.extend(_REQUIREMENT.finditer(value, date.end(), clock.start()))
        tail = value[tail_start:]
        clean_tail = _REQUIREMENT.sub(' ', tail)
        if re.fullmatch(r'[\s,.:()\[\]]*', clean_tail):
            markers.extend(_REQUIREMENT.finditer(tail))
        elif clocks and re.fullmatch(r'[\s,.:()\[\]]*(?:at\s+|by\s+)?[\s,.:()\[\]]*',
                                    _without_clocks(clean_tail), re.I):
            # A complete but contradictory clock may lose its precision while
            # the directly owned date survives. Arbitrary trailing prose cannot.
            owned_clock = None
        else:
            continue
        flags = {not bool(re.search(r'optional|not\s+required', marker.group(0), re.I)) for marker in markers}
        if len(flags) > 1:
            continue  # Contradictory metadata cannot reassign a date.
        if flags:
            header += ' (required)' if flags.pop() else ' (optional)'
        if clocks and owned_clock is None:
            container['_deadline_uncertain_component'] = True
        # This semantic slice contains only proved fields. Citations still use
        # the original container, and local revalidation never claims a fetch.
        header += ' '
        context = header + date.group(0)
        if owned_clock:
            context += ' at ' + owned_clock.group(0)
        return context, len(header)
    return '', 0


def nearest_deadline_time(context, offset, date_length):
    clocks = list(TIME_RE.finditer(context))
    return clocks[0] if len(clocks) == 1 else None


def supported_submission_date(context, offset):
    return bool(context and deadline_kind(context, offset))


def qualify_deadline_sequence(facts, review_queue=None):
    def stage_contexts(fact):
        quote = (fact.get("citation") or {}).get("quote", "")
        contexts = []
        for match in DATE_RE.finditer(quote):
            if parse_document_date(match.group(0)) != fact["date"]:
                continue
            context, offset = deadline_context({"text": quote}, match)
            kind = deadline_kind(context, offset)
            if kind and kind[0] == fact.get("deadline_kind"):
                contexts.append(context)
        return contexts

    def submission_group(fact):
        roman = {value: str(index) for index, value in enumerate(
            ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"), 1)}
        words = {value: str(index) for index, value in enumerate(
            ("ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE", "TEN"), 1)}
        values = {key: {str(fact[key])} for key in ('cycle', 'track', 'application_class')
                  if fact.get(key) and fact.get(key) != 'unspecified'}
        for context in stage_contexts(fact):
            for match in SUBMISSION_GROUP_RE.finditer(context):
                kind = (match.group("kind") or "fiscal_year").casefold()
                token = (match.group("value") or match.group("fy")).upper()
                value = str(int(token)) if token.isdigit() else roman.get(token, words.get(token))
                if kind == "fiscal_year" and len(token) == 2:
                    value = "20" + token
                values.setdefault(kind, set()).add(value)
        return {kind: next(iter(items)) if len(items) == 1 else None for kind, items in values.items()}

    def same_submission_group(left, right):
        return all(not left.get(kind) or not right.get(kind) or left[kind] == right[kind]
                   for kind in left.keys() | right.keys())

    preliminary = [fact for fact in facts if fact.get("type") == "deadline"
                   and fact.get("deadline_kind") != "application" and fact.get('required') is not False]
    full_dates = {fact.get('date') for fact in facts if fact.get('type') == 'deadline'
                  and fact.get('deadline_kind') == 'application'}
    if not preliminary:
        return facts
    kept = []
    for fact in facts:
        if fact.get("type") != "deadline" or fact.get("deadline_kind") != "application":
            kept.append(fact)
            continue
        own_group = submission_group(fact)
        cycle_owned = any(own_group.get(key) for key in ('cycle', 'round', 'fiscal_year', 'phase'))
        if fact.get('field_authority') == 'official_notice_field' and len(full_dates) > 1 and not cycle_owned:
            # Each source-native row is independently a proved submission
            # date. Unknown cross-cycle prerequisite relationships cannot turn
            # a later preliminary row into a reason to delete an earlier full
            # cycle. The access projection separately withholds that relation.
            kept.append(fact)
            continue
        applicable = [item["date"] for item in preliminary
                      if same_submission_group(own_group, submission_group(item))]
        explicit_full = any(re.search(r"\b(?:full|final)\s+(?:application|proposal)\b", context, re.I)
                            for context in stage_contexts(fact))
        if not applicable or (fact["date"] >= max(applicable) and
                              (fact["date"] not in applicable or explicit_full)):
            kept.append(fact)
        elif review_queue is not None:
            review_queue.append({"type": "deadline_stage_order_conflict",
                "label": "Verify the current submission stages; an inconsistent or ambiguous application date was withheld",
                "status": "needs_review",
                "message": "An inconsistent or ambiguous application date was withheld; verify the current official submission stages.",
                "withheld_fact_ids": [fact["id"]]})
    return kept


def cached_deadline_time_supported(fact, match):
    if not fact.get("time"):
        return not fact.get('timezone')
    if not match:
        return False

    def clock(value):
        value = re.sub(r"[.\s]", "", value).upper()
        for pattern in ("%I:%M:%S%p", "%I:%M%p", "%I%p", "%H:%M:%S", "%H:%M"):
            try:
                parsed = datetime.strptime(value, pattern)
                return parsed.hour, parsed.minute, parsed.second
            except ValueError:
                pass
        return None

    def zone(value):
        value = str(value or "").casefold()
        # Preserve established canonical IANA representations; do not equate
        # seasonal abbreviations (EST/EDT), partial names, or unknown zones.
        return {"america/new_york": "eastern", "et": "eastern",
                "america/chicago": "central", "ct": "central",
                "america/denver": "mountain", "mt": "mountain",
                "america/los_angeles": "pacific", "pt": "pacific",
                "america/anchorage": "alaska", "pacific/honolulu": "hawaii"}.get(value, value)

    return (clock(fact["time"]) is not None and clock(fact["time"]) == clock(match.group(1))
            and (not fact.get("timezone") or zone(fact["timezone"]) == zone(deadline_timezone(match))))


def revalidate_cached_deadlines(entry):
    """Recheck old citations locally without claiming a new source retrieval."""
    if entry.get("deadline_extractor_identity") == DEADLINE_EXTRACTOR_IDENTITY:
        return
    prior = entry.get("facts") or []
    kept = []
    uncertain_metadata = []
    for fact in prior:
        if fact.get("type") != "deadline":
            kept.append(fact)
            continue
        quote = (fact.get("citation") or {}).get("quote") or ""
        matches = [match for match in DATE_RE.finditer(quote) if parse_document_date(match.group(0)) == fact.get("date")]
        supported = False
        for match in matches:
            context, offset = deadline_context({"text": quote}, match)
            if not supported_submission_date(context, offset):
                continue
            if fact.get("deadline_kind") != deadline_kind(context, offset)[0]:
                continue
            time_match = nearest_deadline_time(context, offset, len(match.group(0)))
            if not cached_deadline_time_supported(fact, time_match):
                continue
            required = explicit_deadline_requirement(context)
            if required is not None and fact.get('required') is not required:
                continue
            if required is None and fact.get('required') is not None:
                fact = deepcopy(fact)
                fact['required'] = None
                uncertain_metadata.append(fact['id'])
            supported = True
            break
        if supported:
            kept.append(fact)
    kept = qualify_deadline_sequence(kept)
    kept_ids = {fact['id'] for fact in kept}
    removed = [fact["id"] for fact in prior if fact['id'] not in kept_ids]
    if removed or uncertain_metadata:
        entry["facts"] = kept
        entry["deadline_extractor_identity"] = DEADLINE_EXTRACTOR_IDENTITY
        for item in entry.get("review_queue") or []:
            if "evidence_ids" in item:
                item["evidence_ids"] = [identifier for identifier in item["evidence_ids"] if identifier not in removed]
        entry["review_queue"] = [item for item in entry.get("review_queue") or []
                                 if item.get("type") != "deadline_conflict" or item.get("evidence_ids")]
        entry.setdefault("review_queue", []).append({"type": "deadline_evidence_withheld",
            "label": "Verify the current submission stages; unsupported cached submission dates were withheld",
            "status": "needs_review",
            "message": "Unbound or inconsistent submission dates or metadata were withheld; verify the current official submission stages.",
            "withheld_fact_ids": removed, "withheld_metadata_fact_ids": uncertain_metadata})


def extract_deadlines(opportunity_id, containers, document, extracted_at, review_queue=None):
    # Conflict handling must be identical even for callers that do not request
    # the optional diagnostics list.
    review_queue = review_queue if review_queue is not None else []
    facts = notice_schedule.extract_native(sys.modules[__name__], opportunity_id,
        containers, document, extracted_at, review_queue)
    native_dates = {(f['deadline_kind'], f['date']) for f in facts}
    superseded_fields = {(item.get('deadline_kind'), item.get('alternate_date'),
                          (item.get('alternate_citation') or {}).get('page'))
                         for item in review_queue or [] if item.get('type') == 'deadline_source_conflict'}
    seen = {}
    for container in containers:
        if container.get('source_component') == 'nsf_submission_fields':
            continue  # Only the source-native reader owns this component.
        text = container["text"]
        for match in DATE_RE.finditer(text):
            if any(start <= match.start() < end for start, end in container.get('_native_field_values', [])):
                continue  # The supported native field reader owns this value.
            context, offset = deadline_context(container, match)
            kind_result = deadline_kind(context, offset)
            if not supported_submission_date(context, offset):
                if DEADLINE_CUE_RE.search(text):
                    container['_deadline_uncertain_component'] = True
                continue
            parsed = parse_document_date(match.group(0))
            if not parsed:
                continue
            kind, label = kind_result
            identity = (kind, parsed)
            if (kind, parsed, container.get('page')) in superseded_fields:
                continue
            if identity in native_dates:
                continue
            if kind == 'preapplication' and any(
                f['date'] == parsed and f['deadline_kind'] in {'preproposal', 'letter_of_intent'}
                and re.search(r'Pre[\s-]Application\s*\(',
                    (f.get('citation', {}).get('structural_reference') or {}).get('field_label', ''), re.I)
                for f in facts):
                continue
            time_match = nearest_deadline_time(context, offset, len(match.group(0)))
            deadline_time = clean_text(time_match.group(1)) if time_match else None
            timezone_value = deadline_timezone(time_match)
            if identity in seen:
                prior = facts[seen[identity]]
                if not deadline_time or (prior.get("time") and
                        (prior.get("timezone") or prior["time"] != deadline_time or not timezone_value)):
                    continue
            required = explicit_deadline_requirement(context)
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
            fact = make_fact(
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
            if identity in seen:
                facts[seen[identity]] = fact
            else:
                seen[identity] = len(facts)
                facts.append(fact)
            if len(facts) >= 12:
                return finish_deadlines(facts, containers, review_queue)
    return finish_deadlines(facts, containers, review_queue)


def finish_deadlines(facts, containers, review_queue):
    facts = notice_schedule.consolidate_final_period_aliases(sys.modules[__name__], facts)
    # A requirement first found as undated prose is redundant when the local
    # fallback proves its date in the same source clause. Native TBD fields
    # remain independent events, including their own cycle/track boundaries.
    facts = [fact for fact in facts if not (
        fact.get('type') == 'submission_requirement' and not fact.get('field_authority')
        and any(other.get('type') == 'deadline' and other.get('deadline_kind') == fact.get('deadline_kind')
                and other.get('required') == fact.get('required')
                and (fact.get('requirement_citation') or {}).get('quote')
                and clean_text(fact['requirement_citation']['quote']) in clean_text(other.get('citation', {}).get('quote', ''))
                for other in facts))]
    if review_queue is not None and any(c.get('_deadline_uncertain_component') for c in containers):
        review_queue.append({'type': 'deadline_evidence_withheld', 'status': 'needs_review',
            'label': 'Verify official submission dates; ambiguous narrative information was withheld',
            'message': 'Only locally owned submission dates and components are published.'})
    return qualify_deadline_sequence(facts, review_queue)


def extract_award_range(opportunity_id, containers, document, extracted_at):
    """Compatibility wrapper; the document builder retains each typed range."""
    return next((fact for fact in notice_semantics.amount_facts(
        sys.modules[__name__], opportunity_id, containers, document, extracted_at)
        if fact["type"] == "award_range"), None)


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
    return next(iter(notice_semantics.cost_share_facts(
        sys.modules[__name__], opportunity_id, containers, document, extracted_at)), None)


def extract_heading_excerpt(opportunity_id, containers, document, extracted_at, **kwargs):
    return notice_semantics.heading_excerpt(sys.modules[__name__], opportunity_id,
        containers, document, extracted_at, **kwargs)


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


FACT_FAMILIES = {
    "deadline": "deadlines", "submission_requirement": "deadlines", "award_range": "amounts", "program_funding": "amounts",
    "expected_awards": "award_context", "project_duration": "award_context",
    "page_limit": "components", "application_component": "components", "cost_share": "cost_share",
    "eligibility_excerpt": "sections", "review_criteria": "sections", "limited_submission": "limits",
    "investigator_submission_limit": "limits", "institutional_submission_policy": "limits",
    "investigator_submission_policy": "limits", "status_signal": "status",
}


def parser_dependencies():
    versions = {**notice_semantics.SEMANTIC_VERSIONS,
            "deadlines": f"{DEADLINE_EXTRACTOR_IDENTITY}:{notice_schedule.SCHEDULE_VERSION}",
            "award_context": "award-context-1"}
    # Context admission affects every semantic reader, independently of the
    # bytes/structure cache. Same-content revalidation must apply this policy.
    return {family: version + ':primary-program-context-1:substantive-boundaries-2' for family, version in versions.items()}


def extract_document_facts(
    record,
    containers,
    document,
    extracted_at,
    review_queue=None,
    *,
    families=None,
):
    opportunity_id = str(
        record.get("opportunity_id")
        or record.get("opportunity_number")
        or "unknown"
    )
    enabled = set(parser_dependencies()) if families is None else set(families)
    if enabled - set(parser_dependencies()):
        raise ValueError("Unknown semantic extraction family")
    if (urlparse(document.get('url') or '').hostname or '').lower() in {'nsf.gov', 'www.nsf.gov'}:
        # NSF program pages include linked *other* programs below the main
        # program. Their requirements cannot become this opportunity's facts.
        # The section label also preserves this boundary in legacy citations.
        containers = [container for container in containers
                      if (container.get('section') or '').strip().casefold() != 'additional program resources']
    facts = extract_deadlines(
        opportunity_id,
        containers,
        document,
        extracted_at,
        review_queue,
    ) if "deadlines" in enabled else []

    # The explicit NSF date component is an exception to sidebar exclusion
    # for submission fields only. Its descriptions cannot supply other facts.
    containers = [c for c in containers if c.get('source_component') != 'nsf_submission_fields']

    if "amounts" in enabled:
        facts.extend(notice_semantics.amount_facts(
            sys.modules[__name__], opportunity_id, containers, document, extracted_at))

    if "award_context" in enabled:
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

    if "components" in enabled:
        facts.extend(notice_semantics.component_facts(
            sys.modules[__name__], opportunity_id, containers, document, extracted_at))

    if "cost_share" in enabled:
        facts.extend(notice_semantics.cost_share_facts(
            sys.modules[__name__], opportunity_id, containers, document, extracted_at))

    if "sections" in enabled:
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

    if "limits" in enabled:
        facts.extend(notice_semantics.limit_facts(
            sys.modules[__name__], opportunity_id, containers, document, extracted_at))

    if "status" in enabled:
        facts.extend(notice_semantics.status_facts(
            sys.modules[__name__], opportunity_id, containers, document, extracted_at))

    unique = {}
    for fact in facts:
        unique.setdefault(fact["id"], fact)
    return list(unique.values())[:MAX_FACTS]


def structured_fact_conflicts(record, fact):
    """Compare only the same subject and basis; structured facts keep authority."""
    comparisons = []
    if fact.get('type') == 'cost_share' and type(fact.get('value')) is bool:
        comparisons.append(('cost_share_required', fact['value']))
    if (fact.get('type') == 'award_range' and fact.get('basis') == 'total_project'
        and fact.get('cost_basis') in {'total', 'unspecified'} and not fact.get('track')
        and not fact.get('estimate_kind') and not fact.get('applicant_condition')):
        comparisons.extend((field, (fact.get('value') or {}).get(bound))
                           for field, bound in [('award_floor', 'minimum'), ('award_ceiling', 'maximum')])
    return [{'field': field, 'structured_value': record[field], 'notice_value': value}
            for field, value in comparisons if value is not None and record.get(field) is not None
            and record[field] != value]


def structured_deadline_conflicts(record, fact, facts):
    """A source date keeps its own stage/scope when a notice disagrees.

    Explicitly different classes/cycles/tracks and native multi-date fields
    describe independent submissions. A lone unqualified notice date cannot
    replace an authoritative date for the same stage by sorting earlier.
    """
    if fact.get('type') != 'deadline':
        return []
    scope_keys = ('application_class', 'cycle', 'track')
    unknown = (None, '', 'unspecified')
    ref = fact.get('citation', {}).get('structural_reference') or {}
    # A retained native field can explicitly list several submission dates.
    # The field identity and source identity must both match, not just its kind.
    if fact.get('field_authority') == 'official_notice_field' and ref.get('field_id'):
        multi = [f for f in facts if f.get('type') == 'deadline'
                 and f.get('deadline_kind') == fact.get('deadline_kind')
                 and f.get('field_authority') == 'official_notice_field'
                 and (f.get('citation', {}).get('structural_reference') or {}).get('field_id') == ref['field_id']
                 and all(f.get('citation', {}).get(k) == fact.get('citation', {}).get(k)
                         for k in ('document_url', 'sha256', 'page', 'section'))
                 and all(f.get(k) == fact.get(k) for k in scope_keys)]
        if len({f.get('date') for f in multi}) > 1:
            return []
    conflicts = []
    for event in record.get('deadlines') or []:
        if (event.get('evidence_id') or event.get('confidence') != 'official_structured'
            or event.get('kind') != fact.get('deadline_kind') or not event.get('date')
            or event['date'] == fact.get('date')):
            continue
        if any(fact.get(k) not in unknown and event.get(k) != fact[k] for k in scope_keys):
            continue
        window = notice_schedule.explicit_submission_window_end(sys.modules[__name__], event.get('note') or '')
        if (fact.get('field_authority') == 'official_notice_field' and event.get('source_field') == 'CloseDate'
            and window == (event['date'], fact.get('date'))):
            continue  # The structured note itself distinguishes the two events.
        conflicts.append({'field': 'deadline:' + event['kind'], 'structured_value': event['date'],
                          'notice_value': fact.get('date')})
    return conflicts


def build_review_queue(record, facts, changed_since_previous, extraction):
    queue = []
    for fact in facts:
        conflicts = structured_fact_conflicts(record, fact)
        if conflicts:
            queue.append({'type': 'structured_fact_conflict', 'status': 'needs_review',
                'label': 'The official notice and structured record disagree; verify the cited field',
                'evidence_ids': [fact['id']], 'conflicts': conflicts})
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
    supplemental = bool(record.get("source") and record["source"] != "Grants.gov")
    if record.get("primary_document_url"):
        return {
            "url": record["primary_document_url"],
            "name": record.get("primary_document_name"),
            # Only a Grants.gov attachment earns that ownership shortcut.
            "kind": "agency_notice" if supplemental else "primary_notice",
        }
    from scripts.source_documents import document_candidates
    duplicate_primary = next((candidate for candidate in document_candidates(record)
                              if candidate.get('role') == 'primary_notice'), None)
    if duplicate_primary:
        return {'url': duplicate_primary['url'], 'name': duplicate_primary.get('name'), 'kind': 'agency_notice'}
    agency_url = record.get("funding_opportunity_url") or (record.get("detail_page") if supplemental else None)
    if not agency_url:
        agency_url = next((candidate['url'] for candidate in document_candidates(record)
                           if candidate.get('role') == 'agency_notice'), None)
    # Complete headline fields do not prove complete requirements or scientific
    # scope. Every supported official route enters the same bounded queue.
    if agency_url:
        parsed = urlparse(agency_url)
        if parsed.hostname in {'eere-exchange.energy.gov', 'arpa-e-foa.energy.gov', 'netl-exchange.energy.gov'} and not re.fullmatch(
                r'FoaId[0-9a-fA-F-]{36}', unquote(parsed.fragment), re.I):
            # A multi-notice inventory is not the canonical call's evidence.
            # Attachment discovery may still use the separate ownership gate.
            return None
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
    signature = "|".join(str(value or "") for value in values)
    identity = source_scope_identity(source.get("url")) if source else None
    return signature + "|" + identity if identity else signature


def validate_public_url(value, resolver=socket.getaddrinfo):
    parsed = urlparse(str(value or "").strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or any((parsed.hostname or "").rstrip(".").lower() == host
               or (parsed.hostname or "").rstrip(".").lower().endswith("." + host)
               for host in ("pivot.proquest.com", "grantforward.com", "infoedglobal.com", "researchfunding.duke.edu"))
    ):
        raise RuntimeError("Official document URL is not a valid HTTP(S) URL.")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port not in {80, 443}:
            raise RuntimeError("Official document URL uses an unsupported port.")
        addresses = resolver(parsed.hostname, port)
    except OSError as exc:
        raise RuntimeError(
            f"Could not resolve official-document host {parsed.hostname}."
        ) from exc
    if not addresses:
        raise RuntimeError("Official document host has no public addresses.")
    for address in addresses:
        raw = address[4][0]
        ip = ipaddress.ip_address(raw)
        if (
            not ip.is_global
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
    session=None,
):
    if session is None:
        with requests.Session() as anonymous:
            anonymous.trust_env = False
            return download_document(url, headers, timeout=timeout, maximum_bytes=maximum_bytes, session=anonymous)
    current_url = url
    timeouts = timeout if isinstance(timeout, tuple) else (timeout, timeout)
    deadline = time.monotonic() + max(timeouts)
    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/pdf,text/html,text/plain;q=0.8,*/*;q=0.5",
        **{key: value for key, value in (headers or {}).items()
           if key.casefold() in {"accept", "user-agent", "if-none-match", "if-modified-since"}},
    }
    for _ in range(6):
        validate_public_url(current_url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("Official document exceeded its time limit.")
        response = session.get(
            current_url,
            headers=request_headers,
            timeout=tuple(min(limit, remaining / 2) for limit in timeouts),
            stream=True,
            allow_redirects=False,
        )
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise RuntimeError("Official document redirect was missing a location.")
            next_url = urljoin(current_url, location)
            # RFC 9110 redirect fragment inheritance preserves named notices
            # on Exchange listing pages without mixing their sibling content.
            if "#" not in location and urlparse(current_url).fragment:
                next_url += "#" + urlparse(current_url).fragment
            if urlparse(next_url).netloc != urlparse(current_url).netloc:
                request_headers.pop("If-None-Match", None)
                request_headers.pop("If-Modified-Since", None)
            current_url = next_url
            continue
        try:
            if response.status_code == 304:
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
                raise RuntimeError(
                    f"Official document exceeds the {maximum_bytes // 1_048_576} MB limit."
                )
            chunks = []
            size = 0
            for chunk in response.iter_content(chunk_size=65_536):
                if time.monotonic() >= deadline:
                    raise RuntimeError("Official document exceeded its time limit.")
                if not chunk:
                    continue
                size += len(chunk)
                if size > maximum_bytes:
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
                "encoding": response.encoding or "utf-8",
            }
            return result
        finally:
            response.close()
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
    from scripts import subtopic_records, subtopic_segmentation, subtopic_structured

    if subtopic_structured.needs_body_revalidation(entry):
        return True
    return subtopic_records.needs_subtopic_extraction(
        entry,
        enabled=True,
        extractor_version=subtopic_segmentation.extractor_version(),
    )


def referenced_fetch(url):
    """Fetch a referenced source page as text, politely (§6.7, P6.3).

    Function-local import cost is why this is a module-level helper rather than a
    closure: `scripts.sources.http` is the project's one polite client, and using
    it keeps retry, delay and User-Agent behaviour identical to every other
    source. Tests inject their own fetcher and never touch the network.
    """
    from scripts.sources.http import PoliteClient

    return PoliteClient().get_text(url)


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
    from scripts import (
        subtopic_cov4,
        subtopic_records,
        subtopic_referenced,
        subtopic_segmentation,
        subtopic_sources,
        subtopic_structured,
    )
    from scripts.pull_grants import collect_attachments, fetch_detail

    version = subtopic_segmentation.extractor_version()

    # P9.0 first refusal. These are bounded, agency-declared routes over named
    # parents and current attachment lists. A claimed route that collapses
    # returns zero and does not fall through to generic inference; a higher rung
    # is never unioned with a weaker one.
    structured = subtopic_structured.first_refusal(
        record,
        content,
        document,
        detail_fetcher=fetch_detail,
        collector=collect_attachments,
        download=download_document,
        extract_containers=extract_containers,
        as_of=fetched_at[:10],
    )
    if structured is not None:
        gated, structured_cov4 = subtopic_cov4.apply_gate(
            record,
            list(structured.records),
            structured.document or document or {},
        )
        fields = {
            "subtopics": gated,
            "subtopic_method": structured.method,
            "subtopic_extractor_version": version,
            "subtopic_attempts": (),
            "subtopic_cov4": structured_cov4,
            "subtopic_structured": structured.diagnostics,
        }
        if structured.document:
            fields["subtopic_source_document"] = {
                "url": structured.document.get("url"),
                "name": structured.document.get("name"),
                "sha256": structured.document.get("sha256"),
                "source_kind": structured.document.get("source_kind"),
                "attachment_id": structured.document.get("attachment_id"),
            }
        if structured.reason:
            fields["subtopic_reason"] = structured.reason
        return fields

    # §6.7·0 first refusal: a source that *asserts* the parent→child relationship
    # is asked before one that infers it. Today that is exactly one measured
    # source (P6.3, MEAS-7). It answers for one parent and declines for every
    # other record, and declining costs nothing -- the generic path below runs
    # unchanged, so an unhealthy referenced source can never suppress an answer
    # inference would have found.
    referenced_result, referenced_document, referenced_diagnostics = (
        subtopic_referenced.first_refusal(record, fetch=referenced_fetch)
    )
    if referenced_result is not None:
        # Cov4 is applied here too, and it is *supposed* to do nothing. The P6
        # forward obligation is that `referenced` children bypass the classifier
        # at the production call site rather than by never reaching it, so the
        # gate is invoked and its own provenance boundary declines them --
        # `bypassed: 14, classifier_calls: 0` in the diagnostics below is the
        # proof, and a regression test reads exactly that.
        referenced_records, referenced_cov4 = subtopic_cov4.apply_gate(
            record,
            subtopic_records.build_records(
                record,
                referenced_result,
                document=referenced_document,
                as_of=fetched_at[:10],
                # §5.1: the notice delegates to this page, so the rung is
                # `referenced`. Never `native` -- the Army publishes the page,
                # not the relationship.
                provenance=subtopic_records.REFERENCED,
            ),
            referenced_document,
        )
        return {
            "subtopics": referenced_records,
            # Orthogonal to provenance, and genuinely absent: no segmentation
            # layer and no pattern family ran (§5.1).
            "subtopic_method": referenced_result.method,
            "subtopic_extractor_version": version,
            "subtopic_attempts": (),
            "subtopic_source_document": {
                "url": (referenced_document or {}).get("url"),
                "name": (referenced_document or {}).get("name"),
                "sha256": (referenced_document or {}).get("sha256"),
            },
            "subtopic_referenced": referenced_diagnostics,
            "subtopic_cov4": referenced_cov4,
        }

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
        # §18.1 Cov4. The narrowest point that already holds everything the gate
        # needs: `built` carries the parent id, the parent opportunity number,
        # the §5.1 rung, the candidate title and its excerpt; `chosen or
        # document` carries the source URL, name, sha256 and `source_kind`, which
        # is the ownership evidence. No second candidate pipeline is created --
        # this filters the spans `build_records` just produced.
        built, cov4 = subtopic_cov4.apply_gate(record, built, chosen or document)
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
        "subtopic_cov4": cov4,
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
    structure_cache=None,
):
    fetched_at = iso_utc(now)
    content = response["content"]
    if content_kind(content, response.get("content_type"), source.get("name"), source["url"]) == "html":
        content = scoped_html(content, source["url"])
    digest = hashlib.sha256(content).hexdigest()
    previous_document = (previous or {}).get("document") or {}
    previous_hash = previous_document.get("sha256")
    changed_since_previous = bool(previous_hash and previous_hash != digest)

    document_url = resolved_document_url(source, response)
    same_extractor = (previous and previous.get("extractor_identity") == EXTRACTOR_IDENTITY
                      and previous.get("parser_dependencies") == parser_dependencies()
                      and previous.get("source_scope_identity") == source_scope_identity(source["url"]))
    same_route = previous_document.get("url") == document_url
    if previous_hash == digest and same_extractor and same_route:
        entry = deepcopy(previous)
        entry["source_signature"] = source_signature(record, source)
        entry["checked_at"] = fetched_at
        entry.pop("last_attempt_at", None)
        entry["last_error"] = None
        entry["status"] = "current"
        entry.pop('parser_pending', None)
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
        structure_dependencies = notice_structure_cache.identity(entry['document'], source_scope_identity(source['url']))
        missing_structure = structure_cache is not None and structure_cache.read(structure_dependencies) is None
        if (enable_subtopics and backfill_subtopics) or missing_structure:
            containers, _extraction = extract_containers(
                content,
                response.get("content_type"),
                source.get("name"),
                entry["document"].get("url") or source["url"],
            )
            if structure_cache:
                structure_cache.write(structure_dependencies, containers, _extraction)
        if enable_subtopics and backfill_subtopics:
            entry.pop("subtopic_revalidation", None)
            entry.pop("subtopic_reason", None)
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
    if changed_since_previous:
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
    version = (int(previous_document.get("version") or 1) if previous_hash == digest
               else int(previous_document.get("version") or 0) + 1)
    document = {
        "url": document_url,
        "name": source.get("name"),
        "source_kind": source["kind"],
        "content_type": response.get("content_type"),
        "sha256": digest,
        "bytes": len(content),
        "etag": response.get("etag"),
        "last_modified": response.get("last_modified"),
        "version": version,
        "first_seen_at": previous_document.get("first_seen_at", fetched_at) if previous_hash == digest else fetched_at,
        "last_seen_at": fetched_at,
        "changed_since_previous": changed_since_previous,
    }
    structure_dependencies = notice_structure_cache.identity(document, source_scope_identity(source['url']))
    restored = structure_cache.read(structure_dependencies) if structure_cache else None
    if restored is None:
        containers, extraction = extract_containers(content, response.get('content_type'), source.get('name'), document['url'])
        if not any(container.get('text', '').strip() for container in containers):
            raise ValueError('Official document response contains no readable notice text')
        if structure_cache:
            structure_cache.write(structure_dependencies, containers, extraction)
    else:
        containers, extraction = restored
        if not any(container.get('text', '').strip() for container in containers):
            raise ValueError('Official document response contains no readable notice text')
    deadline_review = []
    facts = extract_document_facts(
        record,
        containers,
        document,
        fetched_at,
        deadline_review,
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
    review_queue.extend(deadline_review)
    return {
        "source_signature": source_signature(record, source),
        "source_url": source["url"],
        "extractor_identity": EXTRACTOR_IDENTITY,
        **({"source_scope_identity": source_scope_identity(source["url"])} if source_scope_identity(source["url"]) else {}),
        "deadline_extractor_identity": DEADLINE_EXTRACTOR_IDENTITY,
        "parser_dependencies": parser_dependencies(),
        "structure_identity": structure_dependencies,
        "interpreted_at": fetched_at,
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


def resolved_document_url(source, response):
    """HTTP omits fragments; retain the selector of an actually scoped notice."""
    final_url = response.get('url') or source['url']
    fragment = urlparse(source['url']).fragment
    if fragment and source_scope_identity(source['url']):
        return final_url.split('#', 1)[0] + '#' + fragment
    return final_url


def reparse_from_structure(record, source, previous, now, structure_cache):
    """Reinterpret changed semantic families without claiming a source check."""
    if (not previous or previous.get('last_error') or previous.get('status') not in {'current', 'needs_revalidation'}
        or previous.get('source_scope_identity') != source_scope_identity(source['url'])):
        return None
    dependencies = parser_dependencies()
    old_dependencies = previous.get('parser_dependencies') or {}
    changed = {name for name, version in dependencies.items() if old_dependencies.get(name) != version}
    if not changed:
        return None
    document = previous.get('document') or {}
    restored = structure_cache.read(notice_structure_cache.identity(document, source_scope_identity(source['url'])))
    if restored is None:
        return None
    containers, extraction = restored
    if len(previous.get('facts') or []) >= MAX_FACTS:
        # A shortened projection cannot reveal which omitted facts should now
        # enter the public cap. Rebuild the projection from complete structure.
        changed = set(dependencies)
    review = []
    interpreted_at = iso_utc(now)
    replacements = extract_document_facts(record, containers, document, interpreted_at, review, families=changed)
    retained = [deepcopy(f) for f in previous.get('facts') or [] if FACT_FAMILIES.get(f.get('type')) not in changed]
    order = {name: index for index, name in enumerate(('deadlines', 'amounts', 'award_context', 'components', 'cost_share', 'sections', 'limits', 'status'))}
    facts = sorted(retained + replacements, key=lambda f: order.get(FACT_FAMILIES.get(f.get('type')), 99))[:MAX_FACTS]
    entry = deepcopy(previous)
    entry.pop('parser_pending', None)
    entry.update(facts=facts, parser_dependencies=dependencies, interpreted_at=interpreted_at,
                 extractor_identity=EXTRACTOR_IDENTITY, deadline_extractor_identity=DEADLINE_EXTRACTOR_IDENTITY,
                 status='current', last_error=None)
    entry['review_queue'] = build_review_queue(record, facts, bool(document.get('changed_since_previous')), extraction)
    if 'deadlines' not in changed:
        review.extend(deepcopy([item for item in previous.get('review_queue') or [] if item.get('type') in {
            'deadline_source_conflict', 'deadline_stage_order_conflict', 'deadline_evidence_withheld'}]))
    entry['review_queue'].extend(review)
    entry['parser_migration'] = {'changed_families': sorted(changed),
        'source_retrieved': False, 'source_checked_at': previous.get('checked_at')}
    return entry


def quarantine_legacy_facts(record, source, entry, structure_cache):
    """Retain only locally provable changed facts while full-source work queues.

    A shortened quote can prove a retained assertion, but cannot prove the
    absence of other source facts. Never mark this fallback as a full reparse.
    Unchanged semantic families and source receipts retain their identities.
    """
    dependencies = parser_dependencies()
    changed = {name for name, version in dependencies.items()
               if (entry.get('parser_dependencies') or {}).get(name) != version}
    if not changed or entry.get('parser_pending', {}).get('target_dependencies') == dependencies:
        return
    prior = entry.get('facts') or []
    document = entry.get('document') or {}
    retained, withheld, corrected = [], [], 0
    def retained_citation(candidate, original):
        citation = deepcopy(original)
        reference = candidate.get('citation', {}).get('structural_reference')
        if reference:
            citation['structural_reference'] = deepcopy(reference)
            citation['structural_reference']['basis'] = 'limited_cached_quote'
            if reference.get('field_id'):
                # Offsets in distinct shortened quotes are not one source
                # field even when they coincidentally have the same number.
                quote_hash = hashlib.sha256((original.get('quote') or '').encode('utf-8')).hexdigest()
                citation['structural_reference']['field_id'] = f"quote:{quote_hash}:{reference['field_id']}"
        return citation

    for fact in prior:
        family = FACT_FAMILIES.get(fact.get('type'))
        if family not in changed:
            retained.append(fact)
            continue
        citation = fact.get('citation') or {}
        quote = citation.get('quote') or ''
        # Citation text from a different document cannot revalidate this entry.
        matches = []
        if (quote and document.get('sha256') and citation.get('sha256') == document['sha256']
            and citation.get('document_url') == document.get('url')):
            container = {'text': quote, 'page': citation.get('page'), 'section': citation.get('section')}
            matches = extract_document_facts(record, [container], document,
                citation.get('extracted_at') or entry.get('checked_at'), families={family})
        accepted = next((candidate for candidate in matches
            if candidate.get('type') == fact.get('type') and candidate.get('value') == fact.get('value')
            and (family != 'deadlines' or all(candidate.get(key) == fact.get(key)
                 for key in ('date', 'deadline_kind', 'time', 'timezone')))), None)
        if accepted:
            # Keep the exact source receipt and stable fact ID; enrich its typed
            # meaning only from the supported local assertion, never old guesses.
            accepted.update(id=fact['id'], citation=retained_citation(accepted, citation),
                            interpretation_basis='limited_cached_quote')
            retained.append(accepted)
            if family == 'amounts' and fact.get('type') == 'award_range':
                # Preserve the source's field order when a corrected quote
                # expands one old fact into several independently owned caps.
                retained.pop()
                for candidate in matches:
                    if candidate.get('type') != 'award_range':
                        continue
                    candidate.update(citation=retained_citation(candidate, citation), interpretation_basis='limited_cached_quote')
                    retained.append(candidate)
                    if candidate is not accepted:
                        corrected += 1
                continue
            if family in {'deadlines', 'amounts', 'components'}:
                # One old assertion can share a citation with several complete
                # fields. Retaining it must not discard a separately owned
                # preliminary date or funding track proved by the same quote.
                for candidate in matches:
                    if candidate is accepted or (family == 'deadlines' and candidate.get('field_authority') != 'official_notice_field'):
                        continue
                    if family == 'amounts' and candidate.get('type') != 'award_range':
                        continue
                    if family == 'components' and candidate.get('type') != fact.get('type'):
                        continue
                    candidate.update(citation=retained_citation(candidate, citation), interpretation_basis='limited_cached_quote')
                    retained.append(candidate)
                    corrected += 1
        else:
            withheld.append(fact)
            # A complete explicit local assertion can correct a previous
            # interpretation (for example "cost sharing is not required").
            # This remains quote-based partial recovery, not a full-source
            # reparse or proof that another source assertion is absent.
            if family in {'amounts', 'cost_share', 'limits', 'components', 'sections', 'status', 'deadlines'}:
                for candidate in matches:
                    undated_requirement = family == 'deadlines' and candidate.get('type') == 'submission_requirement'
                    if candidate.get('type') != fact.get('type') and not undated_requirement:
                        continue
                    if family == 'deadlines' and not undated_requirement and not (
                        candidate.get('field_authority') == 'official_notice_field'
                        or (candidate.get('date') == fact.get('date')
                            and candidate.get('deadline_kind') == fact.get('deadline_kind'))):
                        continue
                    candidate.update(citation=retained_citation(candidate, citation),
                        interpretation_basis='limited_cached_quote', replaces_evidence_id=fact['id'])
                    retained.append(candidate)
                    corrected += 1
    receipt = structure_cache.quarantine(document, withheld, changed) if structure_cache and withheld else None
    unique = {}
    for fact in retained:
        # Repeated legacy excerpts may expose the same explicit native field.
        # Consolidate that event without mixing distinct clocks/cycles/tracks.
        key = (fact['type'], tuple(str(fact.get(k)) for k in (
            'date', 'deadline_kind', 'application_class', 'cycle', 'track', 'time', 'timezone',
            'required', 'invitation_required', 'prerequisite'))) if fact['type'] in {'deadline', 'submission_requirement'} else fact['id']
        if fact['type'] == 'award_range':
            key = ('award_range', tuple(str(fact.get(k)) for k in ('value', 'subject', 'track', 'basis',
                'cost_basis', 'funding_basis', 'estimate_kind', 'applicant_condition')))
        unique.setdefault(key, fact)
    # A clipped excerpt may prove only the date while a second receipt from
    # this same document proves the identical event's clock. Consolidate the
    # redundant clockless copy only when the complete clock is uncontested.
    clock_groups = {}
    for fact in unique.values():
        if fact['type'] != 'deadline':
            continue
        key = tuple(str(fact.get(k)) for k in ('date', 'deadline_kind', 'application_class', 'cycle', 'track',
            'required', 'invitation_required', 'prerequisite')) + tuple(fact.get('citation', {}).get(k) for k in ('document_url', 'sha256'))
        clock_groups.setdefault(key, []).append(fact)
    redundant = set()
    for group in clock_groups.values():
        clocks = {(f.get('time'), f.get('timezone')) for f in group if f.get('time')}
        if len(clocks) == 1:
            redundant.update(id(f) for f in group if not f.get('time') and not f.get('timezone'))
    entry['facts'] = notice_schedule.consolidate_preliminary_aliases(
        notice_schedule.consolidate_final_period_aliases(sys.modules[__name__],
            [f for f in unique.values() if id(f) not in redundant]))[:MAX_FACTS]
    entry['parser_pending'] = {'target_dependencies': dependencies, 'changed_families': sorted(changed),
        'reason': 'original_source_structure_required', 'withheld_count': len(withheld),
        'retained_count': len(entry['facts']), 'corrected_count': corrected, 'quarantine_receipt': receipt}
    # These deadlines have already undergone the limited conservative check;
    # the pending marker continues to require full-source recovery.
    entry['deadline_extractor_identity'] = DEADLINE_EXTRACTOR_IDENTITY
    ids = {fact['id'] for fact in entry['facts']}
    entry['review_queue'] = [item for item in entry.get('review_queue') or []
        if not item.get('evidence_ids') or set(item['evidence_ids']).issubset(ids)]
    entry['review_queue'].append({'type': 'parser_revalidation_pending', 'status': 'needs_review',
        'label': 'Verify current official notice details',
        'message': 'Some cached interpretations need the original source structure; retained excerpts do not establish complete coverage.'})


def subtopic_only_candidates(records, *, enabled):
    """Fallback discovery for records with no canonical official document route.

    Complete headline fields no longer exclude an official agency notice from
    shared extraction. This independent bounded pass still explores attachments
    that have not qualified as a primary notice, under its existing safeguards.
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
    previous_store=None,
    prior_checked_at=None,
    recheck_days=14,
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
        "remaining_update_count": 0,
        "agency_url_tried": 0,
        "cached_count": 0,
        "queued_new_count": 0,
        "queued_recheck_count": 0,
        "classifier_run": classifier_run_metrics([]),
    }
    if not enabled:
        return store, metrics
    from scripts import subtopic_sources, subtopic_structured

    candidates = subtopic_only_candidates(records, enabled=True)
    candidate_ids = {opportunity_id for opportunity_id, _ in candidates}
    store = {
        opportunity_id: deepcopy(entry)
        for opportunity_id, entry in (previous_store or {}).items()
        if opportunity_id in candidate_ids
    }
    if prior_checked_at:
        for entry in store.values():
            entry.setdefault("checked_at", prior_checked_at)
    metrics["cached_count"] = len(store)
    unseen = [item for item in candidates if item[0] not in store]
    due = []
    for item in candidates:
        opportunity_id = item[0]
        if opportunity_id not in store:
            continue
        signature = source_signature(item[1], subtopic_sources.subtopic_only_primary(item[1]))
        prior_signature = store[opportunity_id].get("source_signature")
        if prior_signature is not None and prior_signature != signature:
            store[opportunity_id]["status"] = "source_changed"
            due.append(item)
            continue
        if subtopic_structured.needs_body_revalidation(store[opportunity_id]):
            due.append(item)
            continue
        checked_at = store[opportunity_id].get("checked_at")
        try:
            checked = datetime.fromisoformat(
                str(checked_at or "").replace("Z", "+00:00")
            )
        except ValueError:
            due.append(item)
            continue
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
        if checked <= now - timedelta(days=recheck_days):
            due.append(item)
    queue = unseen + due
    metrics["queued_new_count"] = len(unseen)
    metrics["queued_recheck_count"] = len(due)
    metrics["remaining_update_count"] = max(
        0,
        len(queue) - min(len(queue), max_documents),
    )
    fetched_at = iso_utc(now)
    run_entries = []
    for opportunity_id, record in queue[:max_documents]:
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
        fields = subtopic_fields(
            record, content, None, document, fetched_at, True
        ) or {
            "subtopics": [],
            "subtopic_reason": "no_source_or_extractable_text",
            "subtopic_method": "none",
        }
        fields["checked_at"] = fetched_at
        fields["source_signature"] = source_signature(record, source)
        metrics["attempted"] += 1
        if fields.get("subtopics"):
            metrics["with_subtopics"] += 1
        store[opportunity_id] = fields
        run_entries.append(fields)
        if request_delay:
            time.sleep(request_delay)
    metrics["classifier_run"] = classifier_run_metrics(run_entries)
    return store, metrics


def merge_subtopic_sidecar(cache, sources, current_parent_ids, *, as_of):
    """Preserve untouched P9 children while applying this refresh's results.

    The recurring document pass is deliberately budgeted, so ``sources`` is
    only the subset inspected in this run.  Starting from an empty cache would
    therefore erase every uninspected parent.  Current parent membership is
    the sidecar's only currentness axis; prune on that axis, then upsert only
    the parents for which this run produced a subtopic decision.
    """
    from scripts import subtopic_records

    current_parent_ids = {
        str(identifier) for identifier in current_parent_ids
    }
    subtopic_records.retain_current_parents(cache, current_parent_ids)
    for opportunity_id, entry in sources:
        opportunity_id = str(opportunity_id)
        if opportunity_id not in current_parent_ids:
            continue
        invalid_evidence = entry.get("status") and entry["status"] != "current"
        if "subtopics" not in entry and not invalid_evidence:
            continue
        subtopic_records.upsert_parent(
            cache,
            opportunity_id,
            [] if invalid_evidence else entry.get("subtopics") or [],
            as_of=as_of,
            reason=entry.get("subtopic_reason"),
            method=entry.get("subtopic_method"),
        )
    return cache


def due_for_check(entry, signature, now, recheck_days, *, needs_subtopics=False):
    if not entry:
        return True
    # Parser recovery is due independently of HTTP freshness. A failed source
    # keeps its normal retry backoff even when recovery remains pending.
    if (entry.get('parser_dependencies') != parser_dependencies()
        and entry.get('status') != 'failed' and not entry.get('last_error')):
        return True
    # §8.3 insertion 3, gate 1. On a steady-state night nearly every document
    # takes one of §4's three skip gates, so without this the ~1,400 already
    # cached documents are never even candidates and never get subtopics.
    if needs_subtopics and entry.get('status') != 'failed' and not entry.get('last_error'):
        return True
    if entry.get("status") == "needs_revalidation":
        return True
    if entry.get("extractor_identity") not in (None, EXTRACTOR_IDENTITY) and not entry.get('last_error'):
        return True
    if entry.get("source_signature") != signature:
        return True
    checked_at = entry.get("last_attempt_at") or entry.get("checked_at")
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
        "estimated": fact.get('estimated') is True,
        "source": "Official notice (machine extracted)",
        "source_url": fact["citation"].get("document_url"),
        "confidence": fact.get("confidence"),
        "evidence_id": fact["id"],
        "citation": fact["citation"],
        "required": fact.get("required"),
        **{key: deepcopy(fact[key]) for key in (
            'subject', 'stage', 'application_class', 'cycle', 'track', 'track_citation', 'window_start', 'obligation',
            'invitation_required', 'prerequisite', 'requirement_citation', 'prerequisite_citation', 'clock_citation', 'cycle_citation',
            'field_authority', 'parser_version', 'rolling', 'rolling_citation', 'date_qualifier', 'date_qualifier_citation') if key in fact},
    }


def merge_document_entry(record, entry):
    if entry:
        revalidate_cached_deadlines(entry)
    output = deepcopy(record)
    # Remember source-owned values when a new extraction adds conservative
    # flags. Re-enrichment can then undo only its own overrides.
    for key, original in (output.get("document_evidence") or {}).get("source_fields", {}).items():
        if original["present"]:
            output[key] = original["value"]
        else:
            output.pop(key, None)
    source_fields = {key: {"present": key in output, "value": deepcopy(output.get(key))}
                     for key in ("has_preliminary_stage", "preliminary_stage_type", "limited_submission",
                                 "status_verification_required", "actionability_status", "topic_areas")}
    # Reapplying evidence must remove the prior derived deadlines/citations,
    # including on amendment or failure. Source-listed facts keep authority.
    deadlines = []
    for deadline in output.get("deadlines") or []:
        if deadline.get("evidence_id"):
            continue
        deadline = deepcopy(deadline)
        for key, original in deadline.pop('document_source_fields', {}).items():
            if original['present']:
                deadline[key] = original['value']
            else:
                deadline.pop(key, None)
        if deadline.pop("document_evidence_id", None):
            deadline.pop("citation", None)
            deadline.pop("document_confidence", None)
        deadlines.append(deadline)
    if "deadlines" in output:
        output["deadlines"] = deadlines
    output.pop("document_evidence_checked_at", None)
    output.pop("document_status_signals", None)
    output.pop('submission_requirements', None)
    output.pop("limited_submission_review", None)
    previous_program_labels = list(output.pop("document_program_areas", None) or [])
    previous_program_topics = set(program_areas.topics_for(previous_program_labels))
    if previous_program_topics and "topic_areas" not in (record.get("document_evidence") or {}).get("source_fields", {}):
        output["topic_areas"] = [
            topic
            for topic in (output.get("topic_areas") or [])
            if topic not in previous_program_topics
        ]
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
    for fact in facts:
        conflicts = structured_fact_conflicts(output, fact) + structured_deadline_conflicts(output, fact, facts)
        if conflicts:
            fact['reconciliation'] = {'status': 'conflict', 'structured_authority_preserved': True,
                                      'conflicts': conflicts}
            fact['display_value'] = f"{fact.get('display_value') or 'Notice value'} — differs from structured record; verify"
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
    if entry.get("extractor_identity"):
        output["document_evidence"]["dependency_version"] = 2
        output["document_evidence"]["review_queue"] = build_review_queue(
            record, facts, bool((entry.get("document") or {}).get("changed_since_previous")), entry.get("extraction") or {})
        # These explain extraction-time exclusions, which cannot be rebuilt
        # from the remaining facts. Keep them through repeated projections.
        output["document_evidence"]["review_queue"].extend(deepcopy([
            item for item in entry.get("review_queue") or []
            if item.get("type") in {"deadline_stage_order_conflict", "deadline_evidence_withheld", "deadline_source_conflict", "parser_revalidation_pending"}
        ]))

    deadlines = deepcopy(output.get("deadlines") or [])
    for deadline in deadlines:
        window = notice_schedule.explicit_submission_window_end(sys.modules[__name__], deadline.get('note') or '')
        if (window and deadline.get('kind') == 'application' and deadline.get('confidence') == 'official_structured'
            and deadline.get('source_field') == 'CloseDate' and window[0] == deadline.get('date') and any(
                f.get('deadline_kind') == 'application' and f.get('date') == window[1]
                and f.get('field_authority') == 'official_notice_field' for f in facts)):
            deadline.setdefault('document_source_fields', {})['kind'] = {'present': True, 'value': deadline['kind']}
            deadline['kind'] = 'submission'
        # An estimated XML close date can describe a preliminary window. Its
        # own closing-date explanation must prove the same stage/date as the
        # source notice before refining the generic projection label. Preserve
        # the source value, estimate flag, clock, note and receipt verbatim.
        if (deadline.get('kind') == 'estimated_application' and deadline.get('confidence') == 'official_estimate'
            and deadline.get('source_field') == 'EstimatedSynopsisCloseDate'):
            windows = list(notice_schedule.submission_windows(sys.modules[__name__], deadline.get('note') or ''))
            if (len(windows) == 1 and windows[0][2] == deadline.get('date') and any(
                f.get('type') == 'deadline' and f.get('deadline_kind') == 'letter_of_intent'
                and f.get('date') == deadline.get('date') and f.get('field_authority') == 'official_notice_field' for f in facts)):
                deadline.setdefault('document_source_fields', {})['kind'] = {'present': True, 'value': deadline['kind']}
                deadline['kind'] = 'letter_of_intent'
        # A source listing's generic application default is weaker than a
        # named field on that same official page. Refine only a unique owned
        # stage at the exact listed date; never reinterpret structured fields.
        if (deadline.get('kind') == 'application' and deadline.get('confidence') == 'source_listed'
            and deadline.get('source_field') == 'source listing'):
            owned = [fact for fact in facts if fact.get('type') == 'deadline'
                and fact.get('field_authority') == 'official_notice_field'
                and fact.get('date') == deadline.get('date')
                and fact.get('citation', {}).get('document_url') == deadline.get('source_url')]
            stages = {fact.get('deadline_kind') for fact in owned}
            if len(stages) == 1 and next(iter(stages)) in {'preapplication', 'preproposal', 'concept_paper', 'white_paper', 'letter_of_intent'}:
                deadline.setdefault('document_source_fields', {})['kind'] = {'present': True, 'value': deadline['kind']}
                deadline['kind'] = next(iter(stages))
    output['submission_requirements'] = [citation_deadline(fact) for fact in facts
                                       if fact.get('type') == 'submission_requirement']
    for fact in facts:
        if fact.get("type") != "deadline":
            continue
        if structured_deadline_conflicts(output, fact, facts):
            output['document_evidence']['review_queue'].append({'type': 'deadline_source_conflict',
                'status': 'needs_review', 'label': 'Application dates differ; structured date retained',
                'evidence_ids': [fact['id']], 'conflicts': fact['reconciliation']['conflicts']})
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
                and all(deadline.get(key) in (None, 'unspecified', fact.get(key))
                        or fact.get(key) in (None, 'unspecified') for key in ('application_class', 'cycle', 'track'))
            ),
            None,
        )
        if duplicate:
            duplicate["document_evidence_id"] = fact["id"]
            duplicate["citation"] = fact["citation"]
            duplicate["document_confidence"] = fact["confidence"]
            enriched = citation_deadline(fact)
            conflicts = [{'field': key, 'structured_value': duplicate[key], 'notice_value': enriched[key]}
                         for key in ('time', 'timezone', 'required', 'invitation_required')
                         if duplicate.get(key) is not None and enriched.get(key) is not None
                         and duplicate[key] != enriched[key]]
            if conflicts:
                output['document_evidence']['review_queue'].append({'type': 'deadline_source_conflict',
                    'status': 'needs_review', 'label': 'Submission metadata differs; structured values retained',
                    'evidence_ids': [fact['id']], 'conflicts': conflicts})
            for key in ('time', 'timezone', 'stage', 'application_class', 'cycle', 'track', 'track_citation', 'window_start', 'required', 'obligation',
                        'invitation_required', 'prerequisite', 'requirement_citation', 'prerequisite_citation', 'clock_citation', 'cycle_citation',
                        'date_qualifier', 'date_qualifier_citation'):
                if duplicate.get(key) in (None, 'unspecified', 'unknown') and enriched.get(key) not in (None, 'unspecified', 'unknown'):
                    duplicate.setdefault('document_source_fields', {})[key] = {'present': key in duplicate, 'value': duplicate.get(key)}
                    duplicate[key] = enriched[key]
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
    elif output.get('limited_submission_source') == 'synopsis_heuristic' and any(
        fact.get('type') == 'institutional_submission_policy' and (fact.get('value') or {}).get('unlimited')
        for fact in facts):
        output['limited_submission'] = False

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
    program_area_hits = validated_program_area_hits(entry)
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
    if entry.get("extractor_identity"):
        output["document_evidence"]["source_fields"] = {
            key: value for key, value in source_fields.items()
            if key == "topic_areas" or output.get(key) != value["value"] or (key in output) != value["present"]
        }
    return output


def validated_program_area_hits(entry):
    """Return only cached program-area hits still supported by their quote.

    The controlled recognizers can be tightened after a false positive is
    discovered. Revalidating the cache as well as the browser record prevents
    a stale derived hit from returning on a later zero-fetch refresh.
    """
    patterns_by_label = {
        label: pattern for label, _, pattern in program_areas.ENTRIES
    }
    return [
        hit
        for hit in (entry.get("program_areas") or [])
        if patterns_by_label.get(hit.get("label"))
        and patterns_by_label[hit["label"]].search(
            ((hit.get("citation") or {}).get("quote") or "")
        )
    ]


def revalidate_program_areas_only(catalog, cache, *, now=None):
    """Rebuild only derived program-area fields after a recognizer change.

    This maintenance path deliberately leaves deadline, currentness, and other
    document-evidence fields untouched. It lets a controlled-vocabulary bug be
    repaired incrementally without turning the repair into a broad catalog
    refresh.
    """
    now = now or utc_now()
    output = deepcopy(catalog)
    cached_records = cache.setdefault("records", {})
    changed_ids = set()
    for opportunity_id, entry in cached_records.items():
        previous = list(entry.get("program_areas") or [])
        current = validated_program_area_hits(entry)
        if current != previous:
            entry["program_areas"] = current
            changed_ids.add(str(opportunity_id))

    rebuilt_records = []
    derived_keys = ("topic_areas", "document_program_areas", "document_search_text")
    for record in output["opportunities"]:
        opportunity_id = str(
            record.get("opportunity_id")
            or record.get("opportunity_number")
            or ""
        )
        if opportunity_id not in changed_ids:
            rebuilt_records.append(record)
            continue
        merged = merge_document_entry(record, cached_records.get(opportunity_id))
        rebuilt = deepcopy(record)
        for key in derived_keys:
            if key in merged:
                rebuilt[key] = merged[key]
            else:
                rebuilt.pop(key, None)
        rebuilt_records.append(rebuilt)

    output["opportunities"] = rebuilt_records
    output["search_index"] = build_search_index(rebuilt_records)
    output["document_evidence_generated_at"] = iso_utc(now)
    cache["generated_at"] = iso_utc(now)
    return output, cache, sorted(changed_ids)


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


def classifier_run_metrics(entries):
    """Aggregate the classifier usage generated by this refresh only."""
    totals = {
        "classifier_calls": 0,
        "api_requests": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "usage_reported_calls": 0,
        "usage_unreported_requests": 0,
        "classifier_errors": {},
    }
    for entry in entries:
        diagnostics = (entry or {}).get("subtopic_cov4") or {}
        for key in (
            "classifier_calls",
            "api_requests",
            "input_tokens",
            "output_tokens",
            "usage_reported_calls",
            "usage_unreported_requests",
        ):
            try:
                totals[key] += max(0, int(diagnostics.get(key) or 0))
            except (TypeError, ValueError):
                continue
        for error, count in (diagnostics.get("classifier_errors") or {}).items():
            try:
                amount = max(0, int(count or 0))
            except (TypeError, ValueError):
                continue
            totals["classifier_errors"][str(error)] = (
                totals["classifier_errors"].get(str(error), 0) + amount
            )
    totals["classifier_errors"] = dict(
        sorted(totals["classifier_errors"].items())
    )
    return totals


def validate_refresh_health(metrics, minimum_attempts=5, maximum_failure_rate=0.8):
    classifier = (metrics.get("subtopics") or {}).get("classifier_run") or {}
    classifier_errors = sum(
        max(0, int(count or 0))
        for count in (classifier.get("classifier_errors") or {}).values()
    )
    if classifier_errors:
        raise RuntimeError(
            "Subtopic classifier failed closed: "
            f"{classifier_errors} call(s) reported errors."
        )
    usage_unreported = max(
        0, int(classifier.get("usage_unreported_requests") or 0)
    )
    if usage_unreported:
        raise RuntimeError(
            "Subtopic classifier usage is not fully auditable: "
            f"{usage_unreported} API request(s) omitted token usage."
        )

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


def withhold_outdated_topic_bodies(entry, structure_cache):
    """Invalidate only superseded scientific-body interpretations before work.

    Keep source-check timestamps and the old parser identity: the normal
    bounded backfill queue must still recover this parent's source bodies.
    The empty decision also removes its dependent sidecar scopes and teams.
    """
    from scripts import subtopic_structured
    if not subtopic_structured.needs_body_revalidation(entry):
        return
    prior = entry.get("subtopics") or []
    if prior:
        receipt = structure_cache.quarantine(
            entry.get("subtopic_source_document") or entry.get("document") or {},
            prior, {"scientific_topic_bodies"})
        entry["subtopic_revalidation"] = {"reason": "scientific_body_parser_changed",
            "withheld_count": len(prior), "quarantine_receipt": receipt,
            "target_version": subtopic_structured.HGEO_BODY_VERSION}
    entry["subtopics"] = []
    entry["subtopic_reason"] = "scientific_body_revalidation_pending"


def enrich_document_evidence(
    catalog,
    cache,
    *,
    max_documents=45,
    max_subtopic_documents=45,
    request_delay=0.2,
    recheck_days=14,
    fetcher=download_document,
    now=None,
    enable_subtopics=False,
    structure_cache=None,
):
    now = now or utc_now()
    structure_cache = structure_cache if structure_cache is not None else notice_structure_cache.StructureCache()
    prune_cache_to_catalog(cache, catalog)
    cached_records = cache.setdefault("records", {})
    records = catalog["opportunities"]
    classifier_run_entries = []
    for entry in cached_records.values():
        entry["archived_from_catalog_at"] = None
        if entry.get("program_areas"):
            entry["program_areas"] = validated_program_area_hits(entry)

    if enable_subtopics:
        for entry in list(cached_records.values()) + list((cache.get("subtopic_only") or {}).values()):
            withhold_outdated_topic_bodies(entry, structure_cache)

    candidates = []
    for record in records:
        opportunity_id = str(
            record.get("opportunity_id")
            or record.get("opportunity_number")
            or ""
        )
        source = source_for_record(record)
        entry = cached_records.get(opportunity_id)
        if entry:
            prior_url = entry.get("source_url") or str(entry.get("source_signature") or "").split("|", 1)[0]
            if not source or (prior_url and prior_url != source["url"]):
                entry["status"] = "source_changed"
            elif source_scope_identity(source["url"]) != entry.get("source_scope_identity"):
                entry["status"] = "needs_revalidation"
        if not opportunity_id or not source:
            continue
        signature = source_signature(record, source)
        source_recheck_days = (
            recheck_days
            if record.get("primary_document_url")
            else max(30, recheck_days)
        )
        backfill = needs_subtopics(entry, enable_subtopics)
        if due_for_check(
            entry, signature, now, source_recheck_days, needs_subtopics=backfill
        ):
            candidates.append((record, source, signature, entry, backfill))
    candidates.sort(
        key=lambda item: (
            0 if (item[3] or {}).get("subtopic_reason") == "scientific_body_revalidation_pending" else 1,
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
    reparsed = requests = 0
    # Recover only bounded full-source projections. All remaining changed
    # families are quarantined before publication, preserving unrelated facts.
    failures = []
    for record, source, signature, previous, backfill in candidates[:max_documents]:
        opportunity_id = str(
            record.get("opportunity_id")
            or record.get("opportunity_number")
        )
        headers = {}
        if previous and not backfill:
            recovered = reparse_from_structure(record, source, previous, now, structure_cache)
            if recovered:
                cached_records[opportunity_id] = previous = recovered
                reparsed += 1
                # Interpretation is not a source freshness check. If a check
                # is also due, this same budget slot still performs it.
                if not due_for_check(previous, signature, now, recheck_days):
                    continue
        previous_document = (previous or {}).get("document") or {}
        # §8.3 insertion 3, gate 2. A 304 returns no body, and you cannot
        # segment bytes you did not receive -- so a document needing backfill
        # asks for the whole thing.
        if (previous and not backfill and previous.get('parser_dependencies') == parser_dependencies()
                and previous.get("source_scope_identity") == source_scope_identity(source["url"])
                and previous_document.get("url") == source["url"]):
            if previous_document.get("etag"):
                headers["If-None-Match"] = previous_document["etag"]
            if previous_document.get("last_modified"):
                headers["If-Modified-Since"] = previous_document[
                    "last_modified"
                ]
        try:
            requests += 1
            response = fetcher(source["url"], headers)
            if response.get("status_code") == 304:
                if not previous or not headers or resolved_document_url(source, response) != previous_document.get("url"):
                    raise ValueError("unbound not-modified response")
                previous["checked_at"] = iso_utc(now)
                previous.pop("last_attempt_at", None)
                previous["status"] = "current"
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
                    structure_cache=structure_cache,
                )
                cached_records[opportunity_id] = entry
                if enable_subtopics:
                    classifier_run_entries.append(entry)
                refreshed += int(extracted)
                not_modified += int(not extracted)
        except Exception as exc:  # noqa: BLE001 - retain other records
            failure = {
                "opportunity_id": opportunity_id,
                "url": source["url"],
                "error": type(exc).__name__,
            }
            failures.append(failure)
            if previous:
                previous["status"] = "failed"
                previous["last_attempt_at"] = iso_utc(now)
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
        entry = cached_records.get(opportunity_id)
        source = source_for_record(record)
        if entry and source and entry.get('status') == 'current' and not entry.get('last_error'):
            quarantine_legacy_facts(record, source, entry, structure_cache)
        from scripts.submission_schedule import project as project_schedule
        merged.append(project_schedule(merge_document_entry(record, cached_records.get(opportunity_id)), now.date()))
    output = deepcopy(catalog)
    output["opportunities"] = merged
    output["search_index"] = build_search_index(merged)
    output["facets"] = facet_counts(merged)
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
    metrics['parser_recovery'] = {'reparsed_from_structure': reparsed, 'source_requests': requests,
        'pending_records': sum(bool(entry.get('parser_pending')) for entry in cached_records.values()),
        'withheld_facts': sum((entry.get('parser_pending') or {}).get('withheld_count', 0) for entry in cached_records.values()),
        'structure_cache': dict(structure_cache.counters)}
    if enable_subtopics:
        # §8.3 insertion 4. Only present with the flag on, so the diagnostics
        # block is byte-identical when it is off.
        metrics["subtopics"] = subtopic_metrics(cached_records)
        # §18.1 Cov1. Runs after the administrative pass and writes nowhere
        # near it: a separate store, a separate cache key, no record entry.
        subtopic_only, subtopic_only_metrics = refresh_subtopics_without_source(
            records,
            max_documents=max_subtopic_documents,
            fetcher=fetcher,
            now=now,
            request_delay=request_delay,
            enabled=True,
            previous_store=cache.get("subtopic_only"),
            prior_checked_at=cache.get("generated_at"),
            recheck_days=recheck_days,
        )
        cache["subtopic_only"] = subtopic_only
        metrics["subtopics"]["subtopic_only"] = subtopic_only_metrics
        subtopic_classifier = subtopic_only_metrics["classifier_run"]
        metrics["subtopics"]["classifier_run"] = classifier_run_metrics(
            classifier_run_entries
            + [{"subtopic_cov4": subtopic_classifier}]
        )
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
        help=(
            "Maximum new or due official sources to retrieve in the "
            "administrative evidence pass (default: 45)."
        ),
    )
    parser.add_argument('--structure-cache', type=Path, default=notice_structure_cache.DEFAULT_ROOT,
                        help='Private normalized source cache; never place inside published data assets.')
    parser.add_argument(
        "--max-subtopic-documents",
        type=int,
        default=45,
        help=(
            "Maximum sources to retrieve in the separate subtopic-only pass "
            "when --enable-subtopics is set (default: 45)."
        ),
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
        "--now",
        type=parse_now,
        default=None,
        help=(
            "Override the current time with a timezone-aware ISO 8601 "
            "timestamp for deterministic offline builds."
        ),
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
    parser.add_argument(
        "--revalidate-program-areas-only",
        action="store_true",
        help=(
            "Revalidate cached controlled program-area hits and rebuild only "
            "their derived catalog/search-index fields; perform no fetches."
        ),
    )
    args = parser.parse_args(argv)
    if args.max_documents < 0:
        parser.error("--max-documents must be non-negative")
    if args.max_subtopic_documents < 0:
        parser.error("--max-subtopic-documents must be non-negative")
    if args.request_delay < 0:
        parser.error("--request-delay must be non-negative")
    if args.recheck_days < 1:
        parser.error("--recheck-days must be at least one")
    return args


def main(argv=None):
    args = parse_args(argv)
    catalog = read_catalog(args.catalog)
    cache = read_cache(args.cache)
    if args.revalidate_program_areas_only:
        enriched, cache, changed_ids = revalidate_program_areas_only(
            catalog,
            cache,
            now=args.now,
        )
        write_cache(cache, args.cache)
        write_catalog(enriched, args.catalog)
        print(
            "Program-area revalidation complete: "
            f"{len(changed_ids)} affected records ({', '.join(changed_ids) or 'none'})."
        )
        return 0
    enriched, cache = enrich_document_evidence(
        catalog,
        cache,
        max_documents=args.max_documents,
        max_subtopic_documents=args.max_subtopic_documents,
        request_delay=args.request_delay,
        recheck_days=args.recheck_days,
        enable_subtopics=args.enable_subtopics,
        now=args.now,
        structure_cache=notice_structure_cache.StructureCache(args.structure_cache),
    )
    write_cache(cache, args.cache)
    if args.enable_subtopics:
        # Written only with the flag on, so the flag-off artifact set is
        # unchanged and §0.5 byte-identity holds by construction.
        from scripts import subtopic_records
        from scripts.currentness import filter_current

        as_of = iso_utc(args.now or utc_now())[:10]
        current_records, _ = filter_current(
            enriched["opportunities"], date.fromisoformat(as_of)
        )
        current_parent_ids = {
            str(
                record.get("opportunity_id")
                or record.get("opportunity_number")
                or ""
            )
            for record in current_records
        }
        current_parent_ids.discard("")
        subtopic_cache = subtopic_records.read_cache(args.subtopic_cache)
        sources = list((cache.get("records") or {}).items())
        # §18.1 Cov1 results carry no evidence entry by design, so they are a
        # second source for the same cache rather than a second cache.
        sources += list((cache.get("subtopic_only") or {}).items())
        merge_subtopic_sidecar(
            subtopic_cache,
            sources,
            current_parent_ids,
            as_of=as_of,
        )
        subtopic_records.write_cache(subtopic_cache, args.subtopic_cache)
    write_catalog(enriched, args.catalog)
    metrics = enriched["diagnostics"]["document_evidence"]
    classifier = (metrics.get("subtopics") or {}).get("classifier_run")
    if classifier is not None:
        payload = json.dumps(classifier, sort_keys=True, separators=(",", ":"))
        print(f"Classifier operational diagnostics: {payload}")
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_path:
            with Path(summary_path).open("a", encoding="utf-8") as summary:
                summary.write("### Classifier operational diagnostics\n\n")
                summary.write(f"```json\n{payload}\n```\n\n")
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
