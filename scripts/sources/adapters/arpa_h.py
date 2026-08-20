"""Current public ARPA-H opportunities from the agency's official list.

Bounded at P9.0: this is not a SAM.gov adapter. The official ARPA-H page is the
currentness authority and links five program/initiative pages, one small-
business page and four rolling Mission Office ISOs. Detail pages supply public
notice IDs and dates when ARPA-H publishes them; reused umbrella ISO numbers
are not misrepresented as the child program's own number.
"""

from __future__ import annotations

from datetime import datetime
from html import unescape
import re
from urllib.parse import urljoin, urlparse

from ..base import CanonicalOpportunity, SourceAdapter
from ..http import PoliteClient
from ..registry import register


LIST_URL = "https://arpa-h.gov/explore-funding/open-funding-opportunities"
BASE_URL = "https://arpa-h.gov"
AGENCY = "Advanced Research Projects Agency for Health (ARPA-H)"

_ANCHOR_RE = re.compile(
    r'<a\b[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.I | re.S,
)
_TAG_RE = re.compile(r"<[^>]+>")
_NOTICE_RE = re.compile(
    r"(?:Solicitation\s+)?Notice\s+ID:\s*([A-Z0-9-]+)", re.I
)
_DATE_RE = re.compile(
    r"(?:Proposal Due|Full Proposal Due|Proposal Package.*?Due|"
    r"Solution Summary Requested by|due no later than)\s*:?\s*"
    r"([A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
    re.I,
)

_CLASSES = {
    "/explore-funding/programs/": "program",
    "/explore-funding/initiatives-and-sprints/": "initiative",
    "/explore-funding/sbir": "small_business",
}
_SHARED_UMBRELLA_SLUGS = frozenset({"stream", "ascent-ibo"})


def _plain(fragment):
    return re.sub(
        r"\s+", " ", unescape(_TAG_RE.sub(" ", fragment or ""))
    ).strip()


def _slug(path):
    return urlparse(path).path.rstrip("/").rsplit("/", 1)[-1]


def _date(text):
    found = _DATE_RE.search(text or "")
    if not found:
        return None
    try:
        return datetime.strptime(found.group(1), "%B %d, %Y").date().isoformat()
    except ValueError:
        return None


def parse_listing(html):
    """The ten official current rows, with class and canonical public URL."""
    rows = []
    seen = set()
    for match in _ANCHOR_RE.finditer(html or ""):
        href = unescape(match.group("href"))
        path = urlparse(href).path
        kind = next(
            (value for prefix, value in _CLASSES.items() if path.startswith(prefix)),
            None,
        )
        if not kind:
            continue
        if path.rstrip("/") in {
            "/explore-funding/programs",
            "/explore-funding/initiatives-and-sprints",
        }:
            continue
        title = _plain(match.group("title"))
        identity = _slug(path)
        if not title or not identity or identity in seen:
            continue
        seen.add(identity)
        rows.append({
            "external_id": identity,
            "title": title,
            "url": urljoin(BASE_URL, href),
            "path": path,
            "opportunity_class": kind,
        })

    plain = _plain(html)
    for office, number in re.findall(
        r"([A-Z][A-Za-z ]+Office ISO)\s*\((ARPA-H-SOL-\d{2}-\d{3})\)",
        plain,
    ):
        identity = number.casefold()
        if identity in seen:
            continue
        seen.add(identity)
        rows.append({
            "external_id": number.upper(),
            "opportunity_number": number.upper(),
            "title": office.strip(),
            "url": LIST_URL,
            "path": None,
            "opportunity_class": "mission_office_iso",
            "description": (
                "ARPA-H Mission Office Innovative Solution Opening; submissions "
                "are accepted on a rolling basis."
            ),
        })
    return rows


class ArpaHAdapter(SourceAdapter):
    slug = "arpa-h"
    display_name = "ARPA-H"
    source_type = "Federal"
    enabled = True
    min_records = 6
    max_records = 30
    retain_on_failure = True

    def __init__(self, client=None):
        super().__init__()
        self._client = client or PoliteClient()

    def fetch(self):
        listing = self._client.get_text(LIST_URL)
        rows = parse_listing(listing)
        detail_pages = {}
        for row in rows:
            if row.get("path"):
                detail_pages[row["path"]] = self._client.get_text(row["url"])
        return {"listing_html": listing, "detail_pages": detail_pages}

    def parse(self, payload):
        rows = parse_listing(payload.get("listing_html") or "")
        class_counts = {}
        for row in rows:
            kind = row["opportunity_class"]
            class_counts[kind] = class_counts.get(kind, 0) + 1
        failures = []
        if len(rows) < self.min_records or len(rows) > self.max_records:
            failures.append(f"row_count_{len(rows)}")
        if class_counts.get("mission_office_iso") != 4:
            failures.append("mission_office_iso_count")
        for required in ("program", "initiative", "small_business"):
            if not class_counts.get(required):
                failures.append(f"missing_{required}")
        if failures:
            raise ValueError(
                "ARPA-H public opportunity canary failed: " + ", ".join(failures)
            )

        opportunities = []
        pages = payload.get("detail_pages") or {}
        for row in rows:
            detail = _plain(pages.get(row.get("path"), ""))
            if row.get("path") and not detail:
                raise ValueError(f"ARPA-H detail page missing for {row['path']}")
            notice = _NOTICE_RE.search(detail)
            number = row.get("opportunity_number")
            if notice and row["external_id"] not in _SHARED_UMBRELLA_SLUGS:
                number = notice.group(1).upper()
            close_date = _date(detail)
            description = row.get("description") or (
                f"Current ARPA-H {row['opportunity_class'].replace('_', ' ')}. "
                f"{detail[:1800]}"
            )
            opportunities.append(CanonicalOpportunity(
                title=row["title"],
                external_id=row["external_id"],
                opportunity_number=number,
                url=row["url"],
                agency=AGENCY,
                description=description,
                close_date=close_date,
                deadline_note=(
                    "Current date published on the official ARPA-H opportunity page."
                    if close_date else None
                ),
                funding_categories=["Health"],
            ))
        self.diagnostics = {
            "official_current_rows": len(rows),
            "class_counts": dict(sorted(class_counts.items())),
            "with_notice_id": sum(bool(item.opportunity_number) for item in opportunities),
            "with_close_date": sum(bool(item.close_date) for item in opportunities),
        }
        return opportunities


register(ArpaHAdapter())
