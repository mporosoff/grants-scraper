"""University of Rochester internal & limited-submission opportunities (InfoReady).

Disabled shell. The public portal exposes competition cards, but the previously
tested PlatformServicesV2 request is undocumented and currently returns HTTP
500 outside the portal. Keep this adapter off until there is a stable,
permissioned ingestion route. The parser remains for future fixture work and
expects a JSON array of competition cards::

    {"cardId", "opportunityId", "title", "description",
     "dueDate": "MM/DD/YYYY HH:MM:SS", "category", "organizer", ...}

This is UR's *internal / limited-submission* list (a curated set of competitions
UR runs), not a mirror of federal FOAs -- it complements the Grants.gov catalog.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

from ..base import CanonicalOpportunity, SourceAdapter
from ..registry import register

LISTING_URL = "https://rochester.infoready4.com/"
COMPETITION_URL = f"{LISTING_URL}#competitionDetail/{{id}}"


def _get(item: dict, *keys):
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def _date_part(value):
    """Convert the portal's UTC card timestamp to the displayed Eastern date."""
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = datetime.strptime(text, "%m/%d/%Y %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
        return parsed.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    except ValueError:
        return text.split()[0]


def _iter_competitions(payload) -> Iterable[dict]:
    if isinstance(payload, dict):
        for key in ("competitions", "Competitions", "cards", "results",
                    "data", "items", "homepageItems"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
        else:
            payload = [payload]
    if not isinstance(payload, list):
        return
    for entry in payload:
        if isinstance(entry, dict):
            yield entry


class URInfoReadyAdapter(SourceAdapter):
    slug = "ur-infoready"
    display_name = "UR InfoReady (internal & limited submissions)"
    source_type = "Internal"
    enabled = False
    min_records = 1
    max_records = 500

    def fetch(self):
        raise RuntimeError(
            "UR InfoReady is a disabled shell pending a stable public ingestion route."
        )

    def parse(self, payload) -> Iterable[CanonicalOpportunity]:
        return self.parse_payload(payload)

    def parse_payload(self, payload) -> list[CanonicalOpportunity]:
        opportunities: list[CanonicalOpportunity] = []
        for item in _iter_competitions(payload):
            title = _get(item, "title", "Title", "name")
            if not title:
                continue
            competition_id = _get(item, "opportunityId", "cardId", "id")
            url = (
                COMPETITION_URL.format(id=competition_id)
                if competition_id else LISTING_URL
            )
            opportunities.append(CanonicalOpportunity(
                external_id=str(competition_id or title),
                title=str(title),
                url=str(url),
                description=_get(item, "description", "Description", "summary"),
                close_date=_date_part(
                    _get(item, "dueDate", "applicationDeadline", "deadline", "closeDate")),
            ))
        return opportunities


register(URInfoReadyAdapter())
