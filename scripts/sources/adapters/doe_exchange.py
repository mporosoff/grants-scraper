"""DOE Exchange adapters, retaining IDs from the former office portals.

The former portals migrated to exchange.energy.gov. Production collection uses
the complete embedded JSON listing and an explicit office partition. The
legacy parser remains available for retained source fixtures and document
evidence. Those pages represented each notice with two anchors::

    <a href="#FoaId<guid>">DE-FOA-0003623</a>
    <a href="#FoaId<guid>">HORNIG ...</a>
    Notice Of Funding Opportunity (NOFO)  5/28/2026 09:30 AM ET  TBD

Only current Notice-of-Funding-Opportunity (NOFO) rows are published. Terminal
source observations remain in diagnostics while the complete source snapshot
withdraws their former records. Existing source slugs and FOA numbers retain
their public IDs across the migration.
"""

from __future__ import annotations

from datetime import date
import hashlib
from html import unescape
import re
from typing import Iterable

from ..base import CanonicalOpportunity, SourceAdapter
from ..http import ACCEPT, USER_AGENT, PoliteClient
from ..registry import register
from .doe_exchange_listing import LIST_URL, MAX_BYTES, parse_listing

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
    primary = ordered[-1][0] if ordered else None
    additional = [
        {"kind": "submission", "date": d.isoformat(), "time": t,
         "timezone": "ET" if t else None, "note": 'Submission stage not established by the listing',
         'stage': 'unknown', 'required': None, 'obligation': 'unknown'}
        for d, t in ordered
    ]
    note = (
        f"Next of {len(future)} open submission dates; later dates are in the details."
        if len(future) > 1 else None
    )
    return (primary.isoformat() if primary else None), additional, office, note


def notice_schedule(html, url, as_of):
    """Reuse the shared native reader on exactly this portal notice group."""
    from scripts import extract_document_evidence as evidence
    try:
        content = evidence.scoped_html(html.encode('utf-8'), url)
    except ValueError:
        return None
    containers, _ = evidence.extract_html_sections(content)
    document = {'url': url, 'sha256': hashlib.sha256(content).hexdigest()}
    facts = evidence.notice_schedule.extract_native(evidence, 'source-field', containers, document, None)
    return [{**evidence.citation_deadline(fact), 'evidence_id': None,
             'source': 'Official Exchange submission field', 'source_field': 'notice submission section',
             'confidence': 'source_listed', 'date_status': 'known' if fact.get('date') else 'unknown'} for fact in facts]


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
        from scripts.extract_document_evidence import download_document

        self.diagnostics = {}
        client = PoliteClient()
        try:
            client._pace()
            response = download_document(LIST_URL,
                {'User-Agent': USER_AGENT, 'Accept': ACCEPT}, timeout=client.timeout,
                maximum_bytes=MAX_BYTES, session=client._session)
            if response['url'] != LIST_URL or response['status_code'] != 200:
                raise ValueError('DOE Exchange complete listing route changed')
            self.diagnostics = {'response_bytes': len(response['content']),
                'response_sha256': hashlib.sha256(response['content']).hexdigest()}
            return response['content'].decode('utf-8', errors='strict')
        finally:
            client._session.close()

    def parse(self, payload) -> Iterable[CanonicalOpportunity]:
        opportunities, diagnostics = parse_listing(payload,
            organization_id=self.organization_id, organization_name=self.organization_name,
            slug=self.slug, as_of=self.context.get('as_of') or date.today(),
            maximum=self.max_records)
        self.diagnostics.update(diagnostics)
        return opportunities

    def collect(self) -> list[dict]:
        records = []
        for opportunity in self.parse(self.fetch()):
            record = opportunity.to_record(slug=self.slug, source=self.display_name,
                source_type=self.source_type)
            # Generic prose cleanup inserts a space after "aspx?" before the
            # uppercase query key. These URLs were constructed from a validated
            # GUID on our fixed official route, so retain their exact spelling.
            record['detail_page'] = record['funding_opportunity_url'] = opportunity.url
            record['last_updated'] = opportunity.extra['last_updated']
            for event in record['deadlines']:
                event['source_url'] = opportunity.url
            records.append(record)
        return records

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
            url = f"{self.list_url}#FoaId{row.group('guid')}"
            native = notice_schedule(html, url, as_of)
            if native:
                additional = native
                known_dates = [event['date'] for event in native if event.get('date')]
                close_date = max(known_dates, default=None)
                note = 'See the cited submission stages and any required preliminary step.'
            opportunities.append(CanonicalOpportunity(
                external_id=number,
                opportunity_number=number,
                title=title,
                agency=office or self.display_name,
                url=url,
                close_date=close_date,
                deadline_note=note,
                additional_deadlines=additional,
                extra={'close_date_kind': 'submission_window_end', 'agency_code': 'DOE'},
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
    list_url = LIST_URL
    organization_id = 1
    organization_name = 'ARPA-E'


class EereExchangeAdapter(EEREExchangeAdapter):
    slug = "eere-exchange"
    display_name = "DOE EERE Exchange"
    enabled = True
    list_url = LIST_URL
    organization_id = 2
    organization_name = 'CMEI'


register(ArpaEAdapter())
register(EereExchangeAdapter())
