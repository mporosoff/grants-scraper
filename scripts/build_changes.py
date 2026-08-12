"""Build a rolling, machine-readable catalog change feed.

The daily workflow compares the catalog that was checked out at the start of
the run with the newly generated catalog. Events are retained for 90 days so a
weekly digest does not miss changes that occurred between mailings.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from hashlib import sha1
from pathlib import Path
import json
from xml.sax.saxutils import escape, quoteattr

from scripts.build_feeds import (
    APP_URL,
    FEEDS_BASE,
    best_url,
    load_catalog,
    rfc3339,
)
from scripts.currentness import parse_date, record_is_current

SCHEMA_VERSION = 1
RETENTION_DAYS = 90
CLOSING_SOON_DAYS = 30
EVENT_LABELS = {
    "new": "New opportunity",
    "deadline_changed": "Deadline changed",
    "amended": "Opportunity amended",
    "closing_soon": "Closing soon",
    "closed_or_removed": "Closed or removed",
}


def record_id(record: dict) -> str:
    return str(
        record.get("opportunity_id")
        or record.get("opportunity_number")
        or best_url(record)
    )


def _records(catalog: dict) -> dict[str, dict]:
    return {
        record_id(record): record
        for record in (catalog.get("opportunities") or [])
        if record_id(record)
    }


def _event_id(kind: str, record: dict, changed_at: str, detail: str = "") -> str:
    seed = "|".join((kind, record_id(record), changed_at[:10], detail))
    return sha1(seed.encode("utf-8")).hexdigest()[:20]


def _snapshot(record: dict) -> dict:
    fields = (
        "opportunity_id",
        "opportunity_number",
        "title",
        "agency",
        "source",
        "source_type",
        "status",
        "posted_date",
        "close_date",
        "last_updated",
        "version",
        "topic_areas",
        "disciplines",
        "applicant_types",
        "funding_instruments",
        "award_floor",
        "award_ceiling",
        "detail_page",
        "funding_opportunity_url",
        "primary_document_url",
    )
    return {field: record.get(field) for field in fields}


def diff_catalogs(
    previous: dict,
    current: dict,
    *,
    as_of: date | None = None,
    closing_days: int = CLOSING_SOON_DAYS,
) -> list[dict]:
    """Return actionable events between two catalog snapshots."""
    as_of = as_of or datetime.now(timezone.utc).date()
    changed_at = str(current.get("generated_at") or datetime.now(timezone.utc).isoformat())
    before = _records(previous)
    after = _records(current)
    events: list[dict] = []

    def add(kind, record, detail="", **extra):
        events.append(
            {
                "id": _event_id(kind, record, changed_at, detail),
                "type": kind,
                "label": EVENT_LABELS[kind],
                "changed_at": changed_at,
                "opportunity_id": record_id(record),
                "detail": detail,
                "record": _snapshot(record),
                **extra,
            }
        )

    for ident, record in after.items():
        if not record_is_current(record, as_of)[0]:
            continue
        old = before.get(ident)
        if old is None:
            add("new", record, "First appeared in the public catalog")
        else:
            old_deadline = old.get("close_date")
            new_deadline = record.get("close_date")
            if old_deadline != new_deadline:
                add(
                    "deadline_changed",
                    record,
                    f"{old_deadline or 'not listed'} → {new_deadline or 'not listed'}",
                    old_deadline=old_deadline,
                    new_deadline=new_deadline,
                )
            if (
                old.get("last_updated") != record.get("last_updated")
                or old.get("version") != record.get("version")
            ):
                add("amended", record, "Official source record changed")

        deadline = parse_date(record.get("close_date"))
        if deadline and as_of <= deadline <= as_of + timedelta(days=closing_days):
            old_deadline = parse_date((old or {}).get("close_date"))
            previous_day = as_of - timedelta(days=1)
            already_close = bool(
                old_deadline
                and previous_day
                <= old_deadline
                <= previous_day + timedelta(days=closing_days)
            )
            if not already_close:
                add(
                    "closing_soon",
                    record,
                    f"Deadline {deadline.isoformat()}",
                    deadline=deadline.isoformat(),
                )

    for ident, record in before.items():
        current_record = after.get(ident)
        if current_record and record_is_current(current_record, as_of)[0]:
            continue
        if record_is_current(record, as_of - timedelta(days=1))[0]:
            add(
                "closed_or_removed",
                current_record or record,
                (
                    f"Official status is {current_record.get('status')}"
                    if current_record
                    else "No longer in the current catalog"
                ),
            )

    return events


def merge_history(
    prior_events: list[dict],
    new_events: list[dict],
    *,
    as_of: date | None = None,
    retention_days: int = RETENTION_DAYS,
) -> list[dict]:
    as_of = as_of or datetime.now(timezone.utc).date()
    cutoff = as_of - timedelta(days=retention_days)
    merged = {event.get("id"): event for event in prior_events if event.get("id")}
    merged.update({event["id"]: event for event in new_events})
    kept = []
    for event in merged.values():
        changed = parse_date(event.get("changed_at"))
        if changed and changed >= cutoff:
            kept.append(event)
    return sorted(
        kept,
        key=lambda event: (event.get("changed_at") or "", event.get("id") or ""),
        reverse=True,
    )


def build_atom(events: list[dict], updated: datetime) -> str:
    self_url = f"{FEEDS_BASE}/changes.xml"
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        "  <title>Funding Finder | opportunity changes</title>",
        f"  <link href={quoteattr(self_url)} rel=\"self\"/>",
        f"  <link href={quoteattr(APP_URL)}/>",
        f"  <id>{escape(self_url)}</id>",
        f"  <updated>{rfc3339(updated)}</updated>",
        "  <generator>Funding Finder</generator>",
    ]
    for event in events[:200]:
        record = event.get("record") or {}
        title = record.get("title") or "Untitled opportunity"
        url = best_url(record)
        lines.extend(
            [
                "  <entry>",
                f"    <title>{escape(event.get('label') or 'Opportunity update')}: {escape(title)}</title>",
                f"    <link href={quoteattr(url)}/>",
                f"    <id>urn:funding-finder:change:{escape(event['id'])}</id>",
                f"    <updated>{escape(str(event.get('changed_at')))}</updated>",
                f"    <category term={quoteattr(str(event.get('type') or 'changed'))}/>",
                f"    <summary>{escape(event.get('detail') or '')}</summary>",
                "  </entry>",
            ]
        )
    lines.append("</feed>")
    return "\n".join(lines) + "\n"


def write_change_feed(
    previous: dict,
    current: dict,
    out_dir: Path,
    *,
    as_of: date | None = None,
) -> dict:
    as_of = as_of or datetime.now(timezone.utc).date()
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "changes.json"
    prior = []
    if json_path.exists():
        try:
            prior = json.loads(json_path.read_text(encoding="utf-8")).get("events") or []
        except (OSError, json.JSONDecodeError):
            prior = []
    new_events = diff_catalogs(previous, current, as_of=as_of)
    events = merge_history(prior, new_events, as_of=as_of)
    generated = datetime.now(timezone.utc)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": rfc3339(generated),
        "retention_days": RETENTION_DAYS,
        "events": events,
    }
    json_path.write_text(
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").replace("\u2014", "-").replace("\u2013", "-"),
        encoding="utf-8",
    )
    (out_dir / "changes.xml").write_text(
        build_atom(events, generated).replace("\u2014", "-").replace("\u2013", "-"),
        encoding="utf-8",
    )
    return {
        "new_event_count": len(new_events),
        "retained_event_count": len(events),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build the rolling catalog change feed.")
    parser.add_argument("--previous", required=True)
    parser.add_argument("--current", default="data/opportunities.js")
    parser.add_argument("--out", default="feeds")
    parser.add_argument("--as-of", type=date.fromisoformat)
    args = parser.parse_args(argv)
    summary = write_change_feed(
        load_catalog(Path(args.previous)),
        load_catalog(Path(args.current)),
        Path(args.out),
        as_of=args.as_of,
    )
    print(
        f"Wrote {summary['new_event_count']} new events; "
        f"{summary['retained_event_count']} retained."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
