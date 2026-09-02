"""DOE eXCHANGE portals: ARPA-E eXCHANGE and DOE EERE Exchange.

Both run the same server-rendered ASP.NET platform (there is no JSON/XHR API --
the opportunity list is written into the page HTML, which is why the Network
Fetch/XHR tab is empty). Each open opportunity appears in a summary list as two
anchors sharing a ``#FoaId<guid>`` target (the FOA number, then the title),
followed by the announcement type, the sponsoring office (EERE only), and up to
two submission dates::

    <a href="#FoaId<guid>">DE-FOA-0003623</a>
    <a href="#FoaId<guid>">HORNIG ...</a>
    Notice Of Funding Opportunity (NOFO)  5/28/2026 09:30 AM ET  TBD

Only Notice-of-Funding-Opportunity (NOFO) rows are kept -- Requests for
Information, Teaming Partner Lists, and Notices of Intent are not fundable
opportunities. The next open submission date drives the deadline; later dates
are retained as structured deadlines. Past FOAs are dropped by the merge's
currentness gate. Many ARPA-E/EERE FOAs are not mirrored to Grants.gov, and the
merge dedups any that are.
"""

from __future__ import annotations

from datetime import date
from html import unescape
import re
from typing import Iterable

from ..base import CanonicalOpportunity, SourceAdapter
from ..http import PoliteClient
from ..registry import register

_GUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_FOA_NUMBER = r"(?:[A-Z]{2,4}-)?[A-Z0-9]{2,8}-[A-Z0-9]{3,}"
# One summary row: FOA-number anchor, then everything up to the next FOA-number
# anchor (or end). The middle holds the title anchor + type + office + dates.
_ROW_RE = re.compile(
    r'[?#]foaid=?(?P<guid>' + _GUID + r')"[^>]*>\s*(?P<number>' + _FOA_NUMBER + r')\s*</a>'
    r'(?P<middle>.*?)'
    r'(?=<a\b[^>]*[?#]foaid=?' + _GUID + r'"[^>]*>\s*' + _FOA_NUMBER + r'\s*</a>|\Z)',
    re.IGNORECASE | re.DOTALL,
)
_ANCHOR_RE = re.compile(r"<a\b[^>]*>(?P<text>.*?)</a>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_NOFO_TYPE_RE = re.compile(
    r"^\s*notice of funding opportunity\s*\(NOFO\)",
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r"(\d{1,2})/(\d{1,2})/(\d{4})(?:\s+(\d{1,2}:\d{2}\s*(?:AM|PM))\s*ET)?",
    re.IGNORECASE,
)
_NON_DATE_DEADLINE_RE = re.compile(
    r"\b(?:listed on announcement|TBD)\b",
    re.IGNORECASE,
)


def _strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", unescape(_TAG_RE.sub(" ", html or ""))).strip()


def _deadlines_after_type(text: str, as_of: date):
    """From the NOFO type marker onward, return (next_iso, additional, office, note)."""
    match = _NOFO_TYPE_RE.search(text)
    if not match:
        return None, [], None, None
    window = text[match.end(): match.end() + 200]
    window = re.sub(r"^\s*\(NOFO\)\s*", "", window, flags=re.IGNORECASE)
    first_date = _DATE_RE.search(window)
    non_date_deadline = _NON_DATE_DEADLINE_RE.search(window)
    boundary = min(
        (match.start() for match in (first_date, non_date_deadline) if match),
        default=len(window),
    )
    office = window[:boundary].strip(" -–|")
    office = office or None

    pairs = {}
    for month, day, year, time in _DATE_RE.findall(window):
        try:
            parsed = date(int(year), int(month), int(day))
        except ValueError:
            continue
        pairs.setdefault(parsed, re.sub(r"\s+", " ", time).upper() if time else None)
    ordered = sorted(pairs.items())
    future = [(d, t) for d, t in ordered if d >= as_of]
    primary = future[0][0] if future else (ordered[-1][0] if ordered else None)
    additional = [
        {"kind": "application", "date": d.isoformat(), "time": t,
         "timezone": "ET" if t else None, "note": None}
        for d, t in future[1:]
    ]
    note = (
        f"Next of {len(future)} open submission dates; later dates are in the details."
        if len(future) > 1 else None
    )
    return (primary.isoformat() if primary else None), additional, office, note


class EEREExchangeAdapter(SourceAdapter):
    """Base for the shared ARPA-E / EERE eXCHANGE platform."""

    list_url: str = ""
    source_type = "Federal"
    # A portal can legitimately have no currently actionable NOFOs. Parser
    # health is guarded separately by the recognizable-row count below, so an
    # empty current result does not by itself imply endpoint drift.
    min_records = 0
    max_records = 300

    def fetch(self) -> str:
        return PoliteClient().get_text(self.list_url)

    def parse(self, payload) -> Iterable[CanonicalOpportunity]:
        return self.parse_html(payload)

    def parse_html(self, html: str, as_of: date | None = None) -> list[CanonicalOpportunity]:
        if as_of is None:
            as_of = date.today()
        opportunities: list[CanonicalOpportunity] = []
        rows = list(_ROW_RE.finditer(html or ""))
        if len(rows) < 3:
            raise ValueError(
                "DOE Exchange page did not contain a plausible opportunity-row structure"
            )
        for row in rows:
            middle = row.group("middle")
            title_anchor = _ANCHOR_RE.search(middle)
            title = _strip_tags(title_anchor.group("text")) if title_anchor else ""
            if not title:
                continue
            # The announcement type immediately follows the title anchor.
            # Do not search the whole row: NOI/RFI titles often contain the
            # words "Notice of Funding Opportunity" while remaining non-fundable.
            type_and_dates = _strip_tags(middle[title_anchor.end():])
            if not _NOFO_TYPE_RE.match(type_and_dates):
                continue
            number = row.group("number").upper()
            close_date, additional, office, note = _deadlines_after_type(
                type_and_dates, as_of
            )
            opportunities.append(CanonicalOpportunity(
                external_id=number,
                opportunity_number=number,
                title=title,
                agency=office or self.display_name,
                url=f"{self.list_url}#FoaId{row.group('guid')}",
                close_date=close_date,
                deadline_note=note,
                additional_deadlines=additional,
            ))
        if not opportunities:
            raise ValueError(
                "DOE Exchange page contained rows but no recognizable NOFO types"
            )
        return opportunities


class ArpaEAdapter(EEREExchangeAdapter):
    slug = "arpa-e"
    display_name = "ARPA-E eXCHANGE"
    enabled = True
    list_url = "https://arpa-e-foa.energy.gov/"


class EereExchangeAdapter(EEREExchangeAdapter):
    slug = "eere-exchange"
    display_name = "DOE EERE Exchange"
    enabled = True
    list_url = "https://eere-exchange.energy.gov/"


register(ArpaEAdapter())
register(EereExchangeAdapter())
