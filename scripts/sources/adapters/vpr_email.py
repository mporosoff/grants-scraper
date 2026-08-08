"""University of Rochester VPR funding digest (email piggyback).

Ingests the weekly ``VPR_Funding_Opps@lists.rochester.edu`` digest that the
Office of the Vice President for Research already curates -- limited submissions,
foundation calls (Dreyfus, Sloan, Sony, ACS PRF, ...), and other opportunities
that never reach Grants.gov. We ride on the VPR office's curation instead of
hand-maintaining a list.

Flow
----
1. You auto-forward mail from ``VPR_Funding_Opps@lists.rochester.edu`` to a
   dedicated mailbox (e.g. a Gmail).
2. During the scheduled refresh this adapter reads that mailbox read-only over
   IMAP, parses each digest, and hands the opportunities to the merge layer,
   which dedups against Grants.gov (Grants.gov always wins) and against this
   source's own snapshot, so weekly re-lists collapse onto one record.

Credentials come from environment variables (GitHub Actions secrets), never the
repo:

    VPR_IMAP_HOST      default "imap.gmail.com"
    VPR_IMAP_USER      mailbox address (e.g. urochestercheme@gmail.com)
    VPR_IMAP_PASS      a Gmail *app password* (not the normal password)
    VPR_IMAP_FOLDER    default "INBOX"
    VPR_SENDERS         comma-separated From addresses to accept; default is
                        VPR_Funding_Opps@lists.rochester.edu + cindy.gary@rochester.edu
    VPR_SUBJECT_SENDERS senders that also send unrelated mail; their messages are
                        parsed only if the subject contains VPR_SUBJECT_KEYWORD.
                        Default: cindy.gary@rochester.edu
    VPR_SUBJECT_KEYWORD subject keyword required for VPR_SUBJECT_SENDERS (default "funding")
    VPR_LOOKBACK_DAYS   default "45"

Dedup / "only new, no re-lists"
-------------------------------
Each opportunity gets a stable ``external_id``: the InfoReady competition id from
its link when present, else a detected sponsor opportunity number, else a hash of
the normalized title. The same item re-listed next week maps to the same id.

Segmentation
------------
The digest separates opportunities with blank lines, so we split on blank lines
and treat each block that contains a "strong" field (Deadline / Funding /
Synopsis) as one opportunity. This is robust for well-formed digests; if a real
message omits the blank separators, blocks may merge -- we tune on real mail.

Status: disabled shell until verified against real forwarded mail. The parsing
logic (:func:`extract_opportunities`) is dependency-free and unit-tested against
a saved sample so it can be exercised offline.
"""

from __future__ import annotations

import hashlib
import os
import re
from html.parser import HTMLParser
from typing import Iterable, Optional

from ..base import CanonicalOpportunity, SourceAdapter
from ..registry import register

DEFAULT_SENDERS = [
    "VPR_Funding_Opps@lists.rochester.edu",
    "cindy.gary@rochester.edu",  # subject usually "Updates, Events, Funding opportunities"
]
# Senders who also send unrelated mail: only accept when the subject matches the
# funding keyword. (The VPR listserv is a pure funding digest, so it's exempt.)
SUBJECT_REQUIRED_SENDERS = ["cindy.gary@rochester.edu"]
DEFAULT_SUBJECT_KEYWORD = "funding"

# Collision-proof private-use sentinels for inline links in normalized text.
_L_OPEN, _L_SEP, _L_CLOSE = "", "", ""
_LINK_TOKEN = re.compile(
    _L_OPEN + r"(?P<text>.*?)" + _L_SEP + r"(?P<url>.*?)" + _L_CLOSE, re.DOTALL
)

_GENERIC_LINK_TEXT = re.compile(
    r"^\s*(infoready|home\s*\|\s*grants\.gov|grants\.gov|here|apply|submit"
    r"|sponsor website|click here|read more|learn more|link|pdf|website|opportunity"
    r"|current funding opportunities.*|arl opportunities|onr technology.*"
    r"|\d{4} fellows?|full .*awards? list.*)\s*$",
    re.IGNORECASE,
)

_SECTION_HEADERS = {
    "limited submissions", "external funding", "sbir/sttr", "sbir / sttr",
    "internal funding", "foundation relations", "limited submission opportunities",
}

_FIELD_LABELS = (
    "internal application deadline", "internal deadline", "deadlines", "deadline",
    "funding", "synopsis", "program synopsis", "topic/discipline", "topic",
    "sponsor website", "grant period", "eligibility", "fields of interest",
    "expression of intent deadline", "number of applications allowed", "limited?",
    "next deadlines", "next steps", "competitive", "past grantees",
    "past ur awardees", "criteria for selection",
)
_FIELD_LABEL_RE = re.compile(
    r"^\s*(" + "|".join(re.escape(x) for x in _FIELD_LABELS) + r")\s*:?", re.IGNORECASE
)

# A "strong" label marks a block as a real opportunity (not a header/prose).
_STRONG_FIELD_RE = re.compile(
    r"^\s*(deadline|deadlines|next deadlines|funding|synopsis|program synopsis"
    r"|internal application deadline|expression of intent deadline)\s*:?",
    re.IGNORECASE,
)

_OPP_NUMBER_RE = re.compile(
    r"\b("
    r"(?:PAR|PA|RFA|NOT|PD)-\d{2}-\d{3,4}"
    r"|NSF\s?\d{2}-\d{3}"
    r"|\d{2}-\d{3}"
    r"|W911NF\w+|N0001\w+|FA9550\w+"
    r"|NOFO\w+"
    r")\b"
)
_INFOREADY_ID_RE = re.compile(r"infoready4\.com\D*?(\d{5,})", re.IGNORECASE)
_MONEY_RE = re.compile(r"\$\s?([\d][\d,]{2,})(?:\s?(million|m|k))?", re.IGNORECASE)
_DATE_RE = re.compile(
    r"("
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},?\s+\d{4}"
    r"|\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}/\d{1,2}/\d{4}"
    r")"
)


# --------------------------------------------------------------------------- #
# HTML -> normalized text (links preserved as sentinel tokens)
# --------------------------------------------------------------------------- #
class _HTMLToText(HTMLParser):
    _BLOCK = {"p", "div", "br", "tr", "table", "ul", "ol", "h1", "h2", "h3",
              "h4", "h5", "h6", "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._href: Optional[str] = None
        self._atext: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._atext = []
        elif tag in self._BLOCK:
            self._out.append("\n")

    def handle_endtag(self, tag):
        if tag == "a":
            text = "".join(self._atext).strip()
            url = (self._href or "").strip()
            if text and url and url.lower().startswith(("http", "mailto")):
                self._out.append(f"{_L_OPEN}{text}{_L_SEP}{url}{_L_CLOSE}")
            elif text:
                self._out.append(text)
            self._href = None
            self._atext = []
        elif tag in self._BLOCK:
            self._out.append("\n")

    def handle_data(self, data):
        (self._atext if self._href is not None else self._out).append(data)

    def text(self) -> str:
        raw = "".join(self._out)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", raw)
        return raw.strip()


def normalize_html(html: str) -> str:
    parser = _HTMLToText()
    parser.feed(html or "")
    return parser.text()


def _markdown_links_to_tokens(text: str) -> str:
    return re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        lambda m: f"{_L_OPEN}{m.group(1)}{_L_SEP}{m.group(2)}{_L_CLOSE}",
        text,
    )


def _links_in(segment: str) -> list[tuple[str, str]]:
    return [(m.group("text").strip(), m.group("url").strip())
            for m in _LINK_TOKEN.finditer(segment)]


def _strip_tokens(segment: str) -> str:
    return _LINK_TOKEN.sub(lambda m: m.group("text"), segment)


def _looks_like_title_link(text: str, url: str) -> bool:
    if len(text) < 8 or _GENERIC_LINK_TEXT.match(text):
        return False
    if url.lower().startswith("mailto") or "lists.rochester.edu" in url.lower():
        return False
    if not re.search(r"[A-Za-z]", text):
        return False
    return len(text.split()) >= 2


def _is_field_line(plain: str) -> bool:
    return bool(_FIELD_LABEL_RE.match(plain.strip()))


def _field_value(block_plain: str, label_variants: tuple[str, ...]) -> Optional[str]:
    for line in block_plain.splitlines():
        stripped = line.strip()
        for label in label_variants:
            m = re.match(rf"^\s*{re.escape(label)}\s*:?\s*(.*)$", stripped, re.IGNORECASE)
            if m and m.group(1).strip():
                return m.group(1).strip()
    return None


def _first_date(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    m = _DATE_RE.search(value)
    return m.group(1) if m else None


def _deadlines(block_plain: str) -> tuple[Optional[str], Optional[str]]:
    """Return (sponsor_deadline, internal_deadline) as raw date strings."""
    sponsor = internal = None
    for line in block_plain.splitlines():
        s = line.strip()
        if not re.search(r"deadline|expression of intent", s, re.IGNORECASE):
            continue
        d = _first_date(s)
        if not d:
            continue
        if re.search(r"internal", s, re.IGNORECASE):
            internal = internal or d
        else:
            sponsor = sponsor or d
    return sponsor, internal


def _money(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    m = _MONEY_RE.search(value)
    if not m:
        return None
    try:
        n = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    scale = (m.group(2) or "").lower()
    if scale in ("million", "m"):
        n *= 1_000_000
    elif scale == "k":
        n *= 1_000
    return str(int(n))


def _chunk_title(plains: list[str], links_by_line: list[list[tuple[str, str]]]):
    """Pick (title_text, title_href) for a block: first title-link, else the
    first non-field, non-section, non-generic line."""
    for idx, line_links in enumerate(links_by_line):
        for (t, u) in line_links:
            if _looks_like_title_link(t, u):
                return t, u
    for plain in plains:
        s = plain.strip()
        if (s and len(s) >= 6 and not _is_field_line(plain)
                and s.casefold() not in _SECTION_HEADERS
                and not _GENERIC_LINK_TEXT.match(s)):
            return s, None
    return None, None


def extract_opportunities(normalized_text: str) -> list[dict]:
    """Split the digest on blank lines; each block with a strong field is one
    opportunity."""
    chunks = re.split(r"\n[ \t]*\n", normalized_text)
    opportunities: list[dict] = []

    for chunk in chunks:
        raw_lines = chunk.split("\n")
        plains = [_strip_tokens(l) for l in raw_lines]
        if not any(_STRONG_FIELD_RE.match(p.strip()) for p in plains):
            continue

        links_by_line = [_links_in(l) for l in raw_lines]
        block_plain = "\n".join(plains)
        block_raw = "\n".join(raw_lines)

        title, title_href = _chunk_title(plains, links_by_line)
        if not title:
            continue
        title = re.sub(r"\s+", " ", title).strip().rstrip(":").strip()
        title = re.sub(r"\s*\bNEW\b\s*$", "", title, flags=re.IGNORECASE).strip()
        if len(title) < 6 or title.casefold() in _SECTION_HEADERS:
            continue

        links = _links_in(block_raw)
        infoready = next((u for (_t, u) in links if "infoready4.com" in u.lower()
                          and re.search(r"\d{5,}", u)), None)
        http_links = [u for (_t, u) in links if u.lower().startswith("http")]
        url = infoready or title_href or (http_links[0] if http_links else None)

        external_id = None
        if infoready:
            m = _INFOREADY_ID_RE.search(infoready)
            if m:
                external_id = f"infoready-{m.group(1)}"
        opp_number = None
        num_match = _OPP_NUMBER_RE.search(block_plain)
        if num_match:
            opp_number = num_match.group(1).replace(" ", "")
            external_id = external_id or opp_number
        if not external_id:
            external_id = "vpr-" + hashlib.sha1(
                title.casefold().encode("utf-8")).hexdigest()[:16]

        sponsor_deadline, internal_deadline = _deadlines(block_plain)
        close_date = sponsor_deadline or internal_deadline

        synopsis = _field_value(block_plain, ("synopsis", "program synopsis"))
        synopsis = synopsis[:4000] if synopsis else None
        funding = _field_value(block_plain, ("funding",))
        topic = _field_value(block_plain, ("topic/discipline", "topic",
                                           "fields of interest"))

        note_parts = []
        if internal_deadline and internal_deadline != close_date:
            note_parts.append(f"UR internal deadline {internal_deadline}")
        allowed = _field_value(block_plain, ("number of applications allowed",))
        if allowed:
            allowed = re.sub(r"^\s*from\s+ur:?\s*", "", allowed, flags=re.IGNORECASE)
            note_parts.append(f"Applications allowed from UR: {allowed}")

        additional = []
        if internal_deadline:
            additional.append({
                "kind": "internal",
                "date": internal_deadline,
                "note": "UR internal / limited-submission deadline",
                "confidence": "source_listed",
            })

        opportunities.append({
            "title": title,
            "external_id": external_id,
            "opportunity_number": opp_number,
            "url": url,
            "close_date": close_date,
            "deadline_note": "; ".join(note_parts) or None,
            "description": synopsis,
            "award_ceiling": _money(funding),
            "disciplines": [topic] if topic else [],
            "additional_deadlines": additional,
            "extra": {"raw_funding": funding} if funding else {},
        })

    seen: set[str] = set()
    deduped: list[dict] = []
    for opp in opportunities:
        if opp["external_id"] in seen:
            continue
        seen.add(opp["external_id"])
        deduped.append(opp)
    return deduped


# --------------------------------------------------------------------------- #
# Adapter
# --------------------------------------------------------------------------- #
class VPREmailAdapter(SourceAdapter):
    slug = "vpr-email"
    display_name = "UR VPR funding digest (limited submissions & foundations)"
    source_type = "Internal"
    enabled = False          # OFF until tuned against a real forwarded digest (urldefense
                             # link-unwrapping + Outlook MsoNormal HTML). Flip to True after tuning.
    min_records = 1
    max_records = 500

    def fetch(self):
        import email
        import imaplib
        from datetime import date, timedelta
        from email.header import decode_header, make_header

        host = os.environ.get("VPR_IMAP_HOST", "imap.gmail.com")
        user = os.environ.get("VPR_IMAP_USER")
        password = os.environ.get("VPR_IMAP_PASS")
        folder = os.environ.get("VPR_IMAP_FOLDER", "INBOX")
        senders_env = (os.environ.get("VPR_SENDERS") or os.environ.get("VPR_SENDER")
                       or ",".join(DEFAULT_SENDERS))
        senders = [s.strip().lower() for s in senders_env.split(",") if s.strip()]
        subject_required = [s.strip().lower() for s in os.environ.get(
            "VPR_SUBJECT_SENDERS", ",".join(SUBJECT_REQUIRED_SENDERS)).split(",")
            if s.strip()]
        subject_keyword = os.environ.get(
            "VPR_SUBJECT_KEYWORD", DEFAULT_SUBJECT_KEYWORD).lower()
        lookback = int(os.environ.get("VPR_LOOKBACK_DAYS", "45"))
        if not user or not password:
            raise RuntimeError("VPR_IMAP_USER / VPR_IMAP_PASS not set; cannot fetch mail.")

        since = (date.today() - timedelta(days=lookback)).strftime("%d-%b-%Y")
        messages: list[str] = []
        client = imaplib.IMAP4_SSL(host)
        try:
            client.login(user, password)
            client.select(folder, readonly=True)
            typ, data = client.search(None, "SINCE", since)
            ids = data[0].split() if data and data[0] else []
            for msg_id in ids[-200:]:
                typ, raw = client.fetch(msg_id, "(RFC822)")
                if typ != "OK" or not raw or not raw[0]:
                    continue
                msg = email.message_from_bytes(raw[0][1])
                from_hdr = str(make_header(decode_header(msg.get("From", "")))).lower()
                subj = str(make_header(decode_header(msg.get("Subject", "")))).lower()
                body = self._message_html_or_text(msg)
                # Match the sender in the From header OR the top of the body, so this
                # works whether you *redirect* (sender stays in From) or *forward*
                # (the original sender ends up quoted in the body).
                head = from_hdr + "\n" + (body or "")[:3000].lower()
                matched = next((s for s in senders if s in head), None)
                if not matched:
                    continue
                # Senders that also send unrelated mail must match the subject keyword
                # (checked in the subject and body top, to survive a "Fwd:" prefix).
                if (matched in subject_required and subject_keyword
                        and subject_keyword not in (subj + " " + (body or "")[:800].lower())):
                    continue
                messages.append(body)
        finally:
            try:
                client.logout()
            except Exception:
                pass
        return messages

    @staticmethod
    def _message_html_or_text(msg) -> str:
        html_part = text_part = None
        parts = msg.walk() if msg.is_multipart() else [msg]
        for part in parts:
            if str(part.get("Content-Disposition", "")).startswith("attachment"):
                continue
            ctype = part.get_content_type()
            try:
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                decoded = payload.decode(part.get_content_charset() or "utf-8",
                                         errors="replace")
            except Exception:
                continue
            if ctype == "text/html" and html_part is None:
                html_part = decoded
            elif ctype == "text/plain" and text_part is None:
                text_part = decoded
        return html_part or text_part or ""

    def parse(self, payload) -> Iterable[CanonicalOpportunity]:
        for body in payload or []:
            normalized = normalize_html(body) if "<" in body \
                else _markdown_links_to_tokens(body)
            for item in extract_opportunities(normalized):
                yield self._to_canonical(item)

    def parse_payload(self, raw: str) -> list[CanonicalOpportunity]:
        """Parse one raw HTML/markdown sample (offline tests)."""
        normalized = normalize_html(raw) if "<" in raw \
            else _markdown_links_to_tokens(raw)
        return [self._to_canonical(item) for item in extract_opportunities(normalized)]

    @staticmethod
    def _to_canonical(item: dict) -> CanonicalOpportunity:
        return CanonicalOpportunity(
            title=item["title"],
            external_id=item.get("external_id"),
            opportunity_number=item.get("opportunity_number"),
            url=item.get("url"),
            description=item.get("description"),
            close_date=item.get("close_date"),
            deadline_note=item.get("deadline_note"),
            award_ceiling=item.get("award_ceiling"),
            disciplines=item.get("disciplines") or [],
            additional_deadlines=item.get("additional_deadlines") or [],
            extra=item.get("extra") or {},
        )


register(VPREmailAdapter())
