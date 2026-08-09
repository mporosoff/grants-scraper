"""University of Rochester VPR / Hajim funding digest (email piggyback).

Ingests the weekly funding digest that the Office of the VP for Research and the
Hajim grants office (Cindy Gary) already curate -- limited submissions,
foundation calls (Dreyfus, Sloan, Sony, ACS PRF, ...), agency solicitations, and
SBIR/STTR notices that never reach our Grants.gov catalog. We ride on their
curation instead of hand-maintaining a list.

Flow
----
1. You auto-forward the digests to a dedicated mailbox (a Gmail).
2. During the scheduled refresh this adapter reads that mailbox read-only over
   IMAP, parses each digest, and hands the opportunities to the merge layer,
   which dedups against Grants.gov (Grants.gov wins) and against this source's
   own snapshot, so weekly re-lists collapse onto one record.

Credentials come from environment variables (GitHub Actions secrets), never the
repo: VPR_IMAP_HOST/USER/PASS/FOLDER, VPR_SENDERS, VPR_SUBJECT_SENDERS,
VPR_SUBJECT_KEYWORD, VPR_LOOKBACK_DAYS.

Parsing the real digests
------------------------
These are Microsoft Outlook "MsoNormal" HTML messages. Every visible paragraph
is its own block, and links are wrapped by Proofpoint (``urldefense.com``). The
digest has a clean structural signal we exploit:

* **Section headers** are bold *and* underlined  (Events, Good Stuff,
  Limited Submissions, External Funding, SBIR/STTR).
* **Opportunity titles** are bold (not underlined).
* **Field labels** ("Deadline:", "Funding:", "Synopsis:", ...) are bold with a
  trailing colon.

So we convert the HTML to lines while remembering which lines *begin bold*,
switch on the recognized section headers, and start a new opportunity at each
bold title line inside a fundable section (Limited Submissions / External Funding
/ SBIR-STTR / Internal Funding). Event and "Good Stuff" announcements are skipped.
Proofpoint links are unwrapped back to the real sponsor / InfoReady URLs.

Offline diagnostics:  python -m scripts.sources.adapters.vpr_email path/to.eml
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

# Control-char sentinels (never present in real text) for inline links.
_L_OPEN, _L_SEP, _L_CLOSE = "\x01", "\x02", "\x03"
_LINK_TOKEN = re.compile(
    _L_OPEN + r"(?P<text>.*?)" + _L_SEP + r"(?P<url>.*?)" + _L_CLOSE, re.DOTALL
)

# Recognized digest section headers (bold+underline in the source).
_FUNDABLE_SECTIONS = {
    "limited submissions", "limited submission opportunities",
    "external funding", "sbir/sttr", "sbir / sttr", "internal funding",
    "foundation relations",
}
_SKIP_SECTIONS = {"events", "good stuff", "announcements", "news"}
_ALL_SECTIONS = _FUNDABLE_SECTIONS | _SKIP_SECTIONS

# Field labels may carry a leading qualifier ("Dreyfus Deadline:", "Internal
# Application Deadline:") and trailing words before the colon ("Number of
# Applications Allowed from UR:"), so we match an optional prefix word or two,
# a known keyword, then up to a few non-colon chars, then the colon.
_PREFIX = r"(?:[A-Za-z][\w &/().,'\-]{0,39}\s)?"
_FIELD_KW = (
    r"internal application deadline|expression of intent deadline|next deadlines"
    r"|program synopsis|number of applications allowed|criteria for selection"
    r"|past ur awardees|past grantees|fields? of interest|sponsor website"
    r"|grant period|topic/discipline|next steps|deadlines?|eligibility"
    r"|competitive|funding|synopsis|topic|note|limited"
)
_FIELD_LABEL_RE = re.compile(
    r"^\s*" + _PREFIX + r"(?:" + _FIELD_KW + r")[^:\n]{0,25}:", re.IGNORECASE)
# A "strong" label marks a buffer as a real opportunity (not a stray heading)
# and marks where one opportunity's fields have begun.
_STRONG_KW = (
    r"internal application deadline|expression of intent deadline|next deadlines"
    r"|program synopsis|deadlines?|funding|synopsis"
)
_STRONG_FIELD_RE = re.compile(
    r"^\s*" + _PREFIX + r"(?:" + _STRONG_KW + r")[^:\n]{0,25}:", re.IGNORECASE)

_OPP_NUMBER_RE = re.compile(
    r"\b("
    r"(?:PAR|PA|RFA|NOT|PD)-\d{2}-\d{3,4}"
    r"|NSF\s?\d{2}-\d{3}"
    r"|W911NF\w+|N0001\w+|FA9550\w+"
    r"|NOFO[A-Z0-9]+"
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
# Proofpoint / urldefense unwrapping
# --------------------------------------------------------------------------- #
def unwrap_urldefense(url: str) -> str:
    """Return the real target of a Proofpoint ``urldefense.com`` wrapper.

    Wrapped form: ``https://urldefense.com/v3/__https:/host/path*frag__;RANDOM``
    We take the part between ``__`` and ``__;``, repair the scheme's single
    slash, and drop the ``*``-encoded anchor/query fragment (the base URL still
    resolves). Non-wrapped URLs are returned unchanged.
    """
    if not url or "urldefense.com" not in url.lower():
        return url
    m = re.search(r"/v3/__(.*?)__;", url, re.DOTALL)
    inner = m.group(1) if m else url
    inner = inner.split("*", 1)[0]              # drop *-encoded fragment
    inner = re.sub(r"^(https?):/(?!/)", r"\1://", inner)  # https:/x -> https://x
    return inner.strip()


# --------------------------------------------------------------------------- #
# HTML -> lines (remembering which lines begin bold, links preserved)
# --------------------------------------------------------------------------- #
class _HTMLToLines(HTMLParser):
    _BLOCK = {"p", "div", "br", "tr", "table", "ul", "ol", "li", "h1", "h2",
              "h3", "h4", "h5", "h6", "blockquote"}
    _BOLD = {"b", "strong"}
    _SKIP = {"style", "script", "head"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[dict] = []
        self._cur: list[str] = []
        self._cur_bold: Optional[bool] = None   # bold-ness of first content on line
        self._bold = 0
        self._skip = 0
        self._href: Optional[str] = None
        self._atext: list[str] = []
        self._abold = False

    # line handling ---------------------------------------------------------
    def _flush(self) -> None:
        text = "".join(self._cur)
        if text.strip():
            self.lines.append({"raw": text, "bold": bool(self._cur_bold)})
        self._cur = []
        self._cur_bold = None

    def _add(self, piece: str, bold: bool) -> None:
        if self._cur_bold is None and piece.strip():
            self._cur_bold = bold
        self._cur.append(piece)

    # tags ------------------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
            return
        if tag in self._BLOCK:
            self._flush()
        if tag in self._BOLD:
            self._bold += 1
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._atext = []
            self._abold = self._bold > 0

    def handle_startendtag(self, tag, attrs):
        if tag in self._BLOCK:
            self._flush()

    def handle_endtag(self, tag):
        if tag in self._SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if tag == "a":
            text = "".join(self._atext).strip()
            url = (self._href or "").strip()
            if text and url and url.lower().startswith(("http", "mailto")):
                self._add(f"{_L_OPEN}{text}{_L_SEP}{url}{_L_CLOSE}", self._abold)
            elif text:
                self._add(text, self._abold)
            self._href = None
            self._atext = []
        if tag in self._BOLD and self._bold:
            self._bold -= 1
        if tag in self._BLOCK:
            self._flush()

    def handle_data(self, data):
        if self._skip:
            return
        if self._href is not None:
            self._atext.append(data)
            if self._bold > 0:          # bold may sit *inside* the <a> tag
                self._abold = True
        else:
            self._add(data, self._bold > 0)

    def close_lines(self) -> list[dict]:
        self._flush()
        for ln in self.lines:
            ln["raw"] = re.sub(r"[ \t\xa0]+", " ", ln["raw"]).strip()
            ln["plain"] = _strip_tokens(ln["raw"]).strip()
        return [ln for ln in self.lines if ln["plain"]]


def _strip_tokens(segment: str) -> str:
    return _LINK_TOKEN.sub(lambda m: m.group("text"), segment)


def _links_in(segment: str) -> list[tuple[str, str]]:
    return [(m.group("text").strip(), unwrap_urldefense(m.group("url").strip()))
            for m in _LINK_TOKEN.finditer(segment)]


def _raw_links_in(segment: str) -> list[str]:
    return [m.group("url").strip() for m in _LINK_TOKEN.finditer(segment)]


def html_to_lines(html: str) -> list[dict]:
    parser = _HTMLToLines()
    parser.feed(html or "")
    return parser.close_lines()


def plain_to_lines(text: str) -> list[dict]:
    """Fallback for a text/plain digest: tokenize ``markdown``-ish links and
    treat every non-blank line as (possibly) a title -- bold is unknown, so we
    rely on the strong-field look-ahead in :func:`extract_opportunities`."""
    text = re.sub(
        r"([^\s<]+)<(https?://[^>]+)>",   # "Title<https://real>" (Outlook text form)
        lambda m: f"{_L_OPEN}{m.group(1)}{_L_SEP}{m.group(2)}{_L_CLOSE}", text)
    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        lambda m: f"{_L_OPEN}{m.group(1)}{_L_SEP}{m.group(2)}{_L_CLOSE}", text)
    out = []
    for raw in text.split("\n"):
        raw = re.sub(r"[ \t\xa0]+", " ", raw).strip()
        plain = _strip_tokens(raw).strip()
        if plain:
            out.append({"raw": raw, "plain": plain, "bold": None})
    return out


# --------------------------------------------------------------------------- #
# field helpers
# --------------------------------------------------------------------------- #
def _section_name(plain: str) -> Optional[str]:
    key = re.sub(r"\s+", " ", plain).strip().casefold().rstrip(":")
    return key if key in _ALL_SECTIONS else None


def _is_field_line(plain: str) -> bool:
    return bool(_FIELD_LABEL_RE.match(plain))


def _field_value(lines_plain: list[str], labels: tuple[str, ...]) -> Optional[str]:
    for s in lines_plain:
        for label in labels:
            m = re.match(rf"^\s*{re.escape(label)}\s*:+\s*(.*)$", s, re.IGNORECASE)
            if m and m.group(1).strip():
                return m.group(1).strip()
    return None


def _synopsis(lines_plain: list[str]) -> Optional[str]:
    """Synopsis text: the value after a (Program) Synopsis label, continuing onto
    following non-field lines within the same opportunity block."""
    for i, s in enumerate(lines_plain):
        m = re.match(r"^\s*(?:program\s+)?synopsis\s*:+\s*(.*)$", s, re.IGNORECASE)
        if not m:
            continue
        parts = [m.group(1).strip()] if m.group(1).strip() else []
        for nxt in lines_plain[i + 1:]:
            if _is_field_line(nxt) or _section_name(nxt):
                break
            if re.match(r"(?i)^\s*(if you have any questions|cindy\s*$|cindy gary"
                        r"|assistant dean|hajim school|306 lattimore)", nxt):
                break
            if nxt.strip():
                parts.append(nxt.strip())
        text = " ".join(parts).strip()
        return text[:4000] or None
    return None


def _first_date(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    m = _DATE_RE.search(value)
    return m.group(1) if m else None


def _iso(value: Optional[str]) -> Optional[str]:
    """Best-effort ISO date; else None (we keep the human text in the note)."""
    if not value:
        return None
    import datetime as _dt
    for fmt in ("%B %d, %Y", "%B %d %Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return _dt.datetime.strptime(value.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _deadlines(lines_plain: list[str]) -> tuple[Optional[str], Optional[str]]:
    """(sponsor_deadline_text, internal_deadline_text) as raw date strings."""
    sponsor = internal = None
    for s in lines_plain:
        if not re.search(r"deadline|expression of intent", s, re.IGNORECASE):
            continue
        if re.search(r"nominations?\s+open|opens?\s+on|open\s+on", s, re.IGNORECASE):
            continue  # "Nominations open on July 15" is not the submission deadline
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


def _is_title_line(line: dict, in_fundable: bool) -> bool:
    """A bold, non-field, non-section line inside a fundable section that reads
    like an opportunity heading (not a note, sub-bullet, or prose sentence)."""
    if not in_fundable:
        return False
    plain = line["plain"]
    if len(plain) < 6 or _is_field_line(plain) or _section_name(plain):
        return False
    if line.get("bold") is False:            # HTML said explicitly not bold
        return False
    if plain[0] in "*-•◦‣·–—+" or re.match(r"^o\s", plain):
        return False                          # notes / sub-bullets, never a title
    if plain[:1].islower():
        return False                          # titles start uppercase / an acronym
    words = plain.split()
    if plain.rstrip().endswith(".") and len(words) > 10:
        return False                          # a prose sentence, not a heading
    if (re.search(r"\b(deadline|funding|synopsis|eligibility)\b", plain, re.IGNORECASE)
            and re.search(r"\d", plain) and ":" not in plain):
        return False                          # field continuation ("Deadline September 15 ...")
    return bool(re.search(r"[A-Za-z]", plain))


_FWD_HEADER_RE = re.compile(r"^\s*(from|sent|to|cc|subject|date|reply-to)\s*:", re.IGNORECASE)


def _single_announcement(lines: list[dict]) -> Optional[dict]:
    """Parse a single-opportunity announcement (e.g. the VPR listserv), which has
    no section headers: the Subject line is the title and the whole body is one
    opportunity."""
    title = None
    body_start = 0
    for i, l in enumerate(lines):
        m = re.match(r"^\s*subject\s*:\s*(.+)$", l["plain"], re.IGNORECASE)
        if m:
            title = m.group(1).strip()
            body_start = i + 1
    buf = [l for l in lines[body_start:] if not _FWD_HEADER_RE.match(l["plain"])]
    if title:
        title = re.sub(r"^\s*(fw|fwd|re)\s*:\s*", "", title, flags=re.IGNORECASE)
        title = re.sub(r"^\s*announcing\s+(the\s+launch\s+of\s+)?", "", title,
                       flags=re.IGNORECASE).strip()
    if not title or len(title) < 6:
        for l in buf:
            p = l["plain"]
            if not _is_field_line(p) and len(p) >= 12 and not _section_name(p):
                title = re.sub(r"^\s*we are pleased to announce (the launch of\s+)?",
                               "", p, flags=re.IGNORECASE).strip()
                break
    if not title or len(title) < 6:
        return None
    plains = [l["plain"] for l in buf]
    if not any(_STRONG_FIELD_RE.match(p) or _is_field_line(p) for p in plains):
        return None
    fake = [{"raw": title, "plain": title, "bold": True}] + buf
    return _build_opportunity(fake)


# --------------------------------------------------------------------------- #
# core extraction
# --------------------------------------------------------------------------- #
def extract_from_lines(lines: list[dict]) -> list[dict]:
    have_bold = any(l.get("bold") for l in lines)
    # No fundable section headers -> a single-opportunity announcement.
    if not any(_section_name(l["plain"]) in _FUNDABLE_SECTIONS for l in lines):
        opp = _single_announcement(lines)
        return [opp] if opp else []
    section: Optional[str] = None
    buffers: list[list[dict]] = []
    current: Optional[list[dict]] = None
    current_strong = False   # has the current opportunity reached its fields yet?

    def in_fundable() -> bool:
        return section in _FUNDABLE_SECTIONS

    for idx, line in enumerate(lines):
        sec = _section_name(line["plain"])
        if sec:
            section = sec
            current = None
            current_strong = False
            continue
        if not in_fundable():
            continue

        strong = bool(_STRONG_FIELD_RE.match(line["plain"]))
        candidate = False
        if not strong:
            if have_bold:
                candidate = _is_title_line(line, True)
            else:
                # text/plain: a non-field line followed by a strong field (before
                # the next heading-ish line) starts a new opportunity.
                if not _is_field_line(line["plain"]) and len(line["plain"]) >= 6:
                    for nxt in lines[idx + 1: idx + 12]:
                        if _STRONG_FIELD_RE.match(nxt["plain"]):
                            candidate = True
                            break
                        if (not _is_field_line(nxt["plain"])
                                and not _raw_links_in(nxt["raw"])
                                and len(nxt["plain"]) >= 6
                                and _looks_like_heading(nxt["plain"])):
                            break

        # Only start a new opportunity when we're not already collecting one, or
        # the current one has already reached its fields. This keeps a title's
        # trailing link / sub-announcement lines (all bold) attached to it.
        if candidate and (current is None or current_strong):
            current = [line]
            buffers.append(current)
            current_strong = False
        elif current is not None:
            current.append(line)
            if strong:
                current_strong = True

    opportunities = []
    for buf in buffers:
        opp = _build_opportunity(buf)
        if opp:
            opportunities.append(opp)

    # de-dup by external_id (weekly re-lists collapse)
    seen: set[str] = set()
    deduped = []
    for opp in opportunities:
        if opp["external_id"] in seen:
            continue
        seen.add(opp["external_id"])
        deduped.append(opp)
    return deduped


def _looks_like_heading(plain: str) -> bool:
    """Heuristic for text/plain: title-ish lines are short-ish and titlecased or
    end with NEW; used only to stop run-on in the no-bold fallback."""
    if re.search(r"\bnew\b\s*$", plain, re.IGNORECASE):
        return True
    words = plain.split()
    return len(words) <= 16 and sum(w[:1].isupper() for w in words) >= max(2, len(words) // 2)


def _build_opportunity(buf: list[dict]) -> Optional[dict]:
    plains = [l["plain"] for l in buf]
    # must contain a strong field to count as a fundable opportunity
    if not any(_STRONG_FIELD_RE.match(p) for p in plains):
        return None

    title = re.sub(r"\s+", " ", buf[0]["plain"]).strip().rstrip(":").strip()
    title = re.sub(r"\s*\bNEW\b\s*$", "", title, flags=re.IGNORECASE).strip()
    if len(title) < 6 or _section_name(title):
        return None

    # locate first field label -> links before it are the "top" (real) links
    first_field_idx = next((i for i, p in enumerate(plains) if _is_field_line(p)),
                           len(plains))
    top_links, all_links, raw_links = [], [], []
    for i, line in enumerate(buf):
        ls = _links_in(line["raw"])
        rl = _raw_links_in(line["raw"])
        all_links.extend(ls)
        raw_links.extend(rl)
        if i <= first_field_idx:
            top_links.extend(ls)

    infoready_raw = next((u for u in raw_links if "infoready4.com" in u.lower()), None)
    infoready_id = None
    if infoready_raw:
        m = _INFOREADY_ID_RE.search(infoready_raw)
        infoready_id = m.group(1) if m else None

    def _pick(links):
        for (t, u) in links:
            if not u.lower().startswith("http"):
                continue
            if "lists.rochester.edu" in u.lower():
                continue
            return u
        return None

    url = None
    if infoready_raw:
        url = unwrap_urldefense(infoready_raw)
    url = url or _pick(top_links) or _pick(all_links)

    block_plain = "\n".join(plains)
    if not url:                              # bare (non-anchored) URL fallback
        murl = re.search(r"https?://[^\s<>\"')]+", block_plain)
        if murl:
            url = unwrap_urldefense(murl.group(0))
    opp_number = None
    num_match = _OPP_NUMBER_RE.search(block_plain)
    if num_match:
        opp_number = num_match.group(1).replace(" ", "")

    if infoready_id:
        external_id = f"infoready-{infoready_id}"
    elif opp_number:
        external_id = opp_number
    else:
        external_id = "vpr-" + hashlib.sha1(title.casefold().encode()).hexdigest()[:16]

    sponsor_deadline, internal_deadline = _deadlines(plains)
    close_text = sponsor_deadline or internal_deadline
    close_date = _iso(close_text)   # None unless it parses to a real date

    synopsis = _synopsis(plains)
    funding = _field_value(plains, ("funding",))
    topic = _field_value(plains, ("topic/discipline", "topic", "fields of interest",
                                  "field of interest"))

    note_parts = []
    if close_text and not close_date:
        note_parts.append(f"Deadline (verify): {close_text}")
    if internal_deadline and internal_deadline != sponsor_deadline:
        note_parts.append(f"UR internal deadline {internal_deadline}")
    allowed = _field_value(plains, ("number of applications allowed",))
    if allowed:
        allowed = re.sub(r"^\s*from\s+ur:?\s*", "", allowed, flags=re.IGNORECASE)
        note_parts.append(f"Applications allowed from UR: {allowed}")

    additional = []
    if internal_deadline:
        additional.append({
            "kind": "internal", "date": internal_deadline,
            "note": "UR internal / limited-submission deadline",
            "confidence": "source_listed",
        })

    return {
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
    }


def extract_opportunities(body: str) -> list[dict]:
    """Parse one message body (HTML preferred; text/plain fallback)."""
    lines = html_to_lines(body) if "<" in body else plain_to_lines(body)
    return extract_from_lines(lines)


# --------------------------------------------------------------------------- #
# Adapter
# --------------------------------------------------------------------------- #
class VPREmailAdapter(SourceAdapter):
    slug = "vpr-email"
    display_name = "UR VPR funding digest (limited submissions & foundations)"
    source_type = "Internal"
    enabled = True           # validated against real Cindy (digest) + VPR (single) emails.
    min_records = 0          # 0 is valid (a quiet mailbox week); don't flag degraded.
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
        # Accept any env-provided senders *plus* the built-in defaults, so both
        # the VPR listserv and Cindy's Hajim digest are ingested without needing
        # to edit the (bridge-protected) workflow env.
        senders_env = os.environ.get("VPR_SENDERS") or os.environ.get("VPR_SENDER") or ""
        senders = {s.strip().lower() for s in senders_env.split(",") if s.strip()}
        senders |= {s.lower() for s in DEFAULT_SENDERS}
        senders = list(senders)
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
                # Search the WHOLE body, not just the first few KB: Outlook digests
                # open with a large <style>/MsoNormal block, so the sender line
                # (in a forward's quoted header) sits well past any small cap.
                body_l = (body or "").lower()
                head = from_hdr + "\n" + body_l
                matched = next((s for s in senders if s in head), None)
                if not matched:
                    continue
                if (matched in subject_required and subject_keyword
                        and subject_keyword not in (subj + " " + body_l)):
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
            for item in extract_opportunities(body):
                yield self._to_canonical(item)

    def parse_payload(self, raw: str) -> list[CanonicalOpportunity]:
        """Parse one raw HTML/text sample (offline tests)."""
        return [self._to_canonical(item) for item in extract_opportunities(raw)]

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


# --------------------------------------------------------------------------- #
# Offline diagnostic:  python -m scripts.sources.adapters.vpr_email file.eml
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("usage: python -m scripts.sources.adapters.vpr_email <message.eml>")
        raise SystemExit(2)

    import email
    with open(sys.argv[1], "rb") as fh:
        msg = email.message_from_binary_file(fh)
    body = VPREmailAdapter._message_html_or_text(msg)
    kind = "html" if "<" in body else "text"
    print(f"[body: {len(body)} chars, parsed as {kind}]")
    opps = VPREmailAdapter().parse_payload(body)
    print(f"=== {len(opps)} opportunities ===")
    for o in opps:
        print(f"\n• {o.title}")
        print(f"    id={o.external_id}  num={o.opportunity_number}")
        print(f"    url={o.url}")
        print(f"    close_date={o.close_date}  note={o.deadline_note}")
        print(f"    award_ceiling={o.award_ceiling}  disciplines={o.disciplines}")
        if o.description:
            print(f"    synopsis={o.description[:160]}")
