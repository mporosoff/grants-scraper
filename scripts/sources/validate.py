"""Currentness, actionability, and health checks for external source records.

Before an external record is allowed into the published catalog it must:
- have a title,
- expose at least one official URL (landing page or document),
- carry only plausible dates (no expired close date; no absurd far-future date),
and each source as a whole must return a plausible number of records.

These gates exist because, unlike the Grants.gov feed, external sources have no
upstream guarantees. A record that fails is dropped; a source whose count is
implausible is treated as unhealthy so the merge can keep its last-known-good
snapshot instead of publishing a broken refresh.
"""

from __future__ import annotations

from datetime import date

# A close date more than this many years out is treated as a data error.
MAX_FUTURE_DAYS = 366 * 6


def _official_url(record: dict) -> str | None:
    return (
        record.get("detail_page")
        or record.get("funding_opportunity_url")
        or record.get("primary_document_url")
    )


def record_is_publishable(record: dict, as_of: date) -> tuple[bool, str]:
    """Return ``(ok, reason)`` for a single external record."""
    if not record.get("title"):
        return False, "missing_title"
    if not _official_url(record):
        return False, "missing_official_url"

    close_date = record.get("close_date")
    if close_date:
        try:
            parsed = date.fromisoformat(close_date)
        except (TypeError, ValueError):
            return False, "unparseable_close_date"
        if parsed < as_of:
            return False, "expired"
        if (parsed - as_of).days > MAX_FUTURE_DAYS:
            return False, "implausible_future_date"

    posted_date = record.get("posted_date")
    if posted_date:
        try:
            date.fromisoformat(posted_date)
        except (TypeError, ValueError):
            return False, "unparseable_posted_date"

    return True, "ok"


def filter_publishable(records: list[dict], as_of: date) -> tuple[list[dict], list[dict]]:
    """Split records into ``(kept, dropped)``; dropped carry a reason."""
    kept: list[dict] = []
    dropped: list[dict] = []
    for record in records:
        ok, reason = record_is_publishable(record, as_of)
        if ok:
            kept.append(record)
        else:
            dropped.append(
                {"opportunity_id": record.get("opportunity_id"), "reason": reason}
            )
    return kept, dropped


def within_health_bounds(count: int, minimum, maximum) -> bool:
    """A source's record count must fall within its configured bounds."""
    if minimum is not None and count < minimum:
        return False
    if maximum is not None and count > maximum:
        return False
    return True
