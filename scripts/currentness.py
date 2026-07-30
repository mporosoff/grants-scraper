"""Shared actionability and date gates for published funding records.

The catalog is a static snapshot, so a record that was current when the file
was generated can expire before the next refresh. Browser code mirrors these
small deterministic rules, while Python consumers (feeds and digests) import
them directly.
"""

from __future__ import annotations

from datetime import date, datetime
import re


NON_FUNDING_TITLE_RE = re.compile(
    r"^(?:[A-Z0-9-]+\s+)?(?:"
    r"notice\s+of\s+intent(?:\s+to\s+issue)?\b|"
    r"request\s+for\s+information\b|"
    r"RFI\s*[-:]"
    r")",
    re.IGNORECASE,
)
NOT_ACCEPTING_RE = re.compile(
    r"\b(?:not|isn't|is\s+not)\s+accepting\s+applications?\b|"
    r"\bno\s+applications?\s+(?:are|will\s+be)\s+accepted\b",
    re.IGNORECASE,
)


def parse_date(value) -> date | None:
    """Parse the ISO date family used by the normalized catalog."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(
            str(value).strip().replace("Z", "+00:00")
        ).date()
    except (TypeError, ValueError):
        return None


def non_funding_reason(record: dict) -> str | None:
    """Return a high-confidence reason that a record is informational only."""
    title = str(record.get("title") or "").strip()
    if NON_FUNDING_TITLE_RE.search(title):
        return "informational_notice"

    instruments = {
        str(value).strip().casefold()
        for value in (
            record.get("funding_instrument_codes")
            or record.get("funding_instruments")
            or []
        )
        if value
    }
    description = str(record.get("description") or "")[:2500]
    if instruments and instruments <= {"o", "other"}:
        if NOT_ACCEPTING_RE.search(description):
            return "not_accepting_applications"
    return None


def record_is_current(
    record: dict,
    as_of: date | None = None,
) -> tuple[bool, str]:
    """Return ``(current, reason)`` using only deterministic catalog fields."""
    as_of = as_of or date.today()
    status = str(record.get("status") or "").casefold()
    if status in {
        "closed",
        "archived",
        "cancelled",
        "canceled",
        "withdrawn",
        "expired",
    }:
        return False, status
    if status not in {"posted", "forecasted"}:
        return False, "invalid_status"

    non_funding = non_funding_reason(record)
    if non_funding:
        return False, non_funding

    close_value = record.get("close_date")
    if close_value:
        close_date = parse_date(close_value)
        if close_date is None:
            return False, "invalid_close_date"
        if close_date < as_of:
            return False, "expired"
        return True, "current_by_close_date"

    archive_value = record.get("archive_date")
    if archive_value:
        archive_date = parse_date(archive_value)
        if archive_date is None:
            return False, "invalid_archive_date"
        if archive_date < as_of:
            return False, "archived"

    return True, (
        "rolling" if record.get("rolling") else "undated_verify_status"
    )


def filter_current(
    records: list[dict],
    as_of: date | None = None,
) -> tuple[list[dict], list[dict]]:
    """Split records into current records and compact exclusion diagnostics."""
    as_of = as_of or date.today()
    kept: list[dict] = []
    excluded: list[dict] = []
    for record in records:
        current, reason = record_is_current(record, as_of)
        if current:
            kept.append(record)
        else:
            excluded.append(
                {
                    "opportunity_id": record.get("opportunity_id"),
                    "opportunity_number": record.get("opportunity_number"),
                    "reason": reason,
                }
            )
    return kept, excluded
