"""Generate static Atom feeds from the public catalog.

No backend, no accounts, no personal data: this simply reads the already-public
``data/opportunities.js`` and writes standards-compliant Atom XML files that any
RSS/Atom reader can subscribe to. It runs in the daily pipeline right after the
catalog is (re)built, so the feeds always reflect the newest opportunities.

Feeds written under ``feeds/``:
  - ``all.xml``                  newest opportunities across every source
  - ``topic/<slug>.xml``         one per Topic facet value
  - ``source-type/<slug>.xml``   one per Source-type facet value (Federal, ...)
  - ``index.json`` / ``index.html``  a machine- and human-readable list of feeds

Usage:
    python -m scripts.build_feeds --catalog data/opportunities.js --out feeds
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape, quoteattr

from scripts.currentness import filter_current

SITE_BASE = "https://mporosoff.github.io/grants-scraper"
APP_URL = f"{SITE_BASE}/match_explorer.html"
FEEDS_BASE = f"{SITE_BASE}/feeds"
ALERTS_DOC_URL = (
    "https://github.com/mporosoff/grants-scraper/tree/main/docs/weekly-alerts"
)

# Keep feeds a readable size; readers only need the recent window.
ALL_LIMIT = 100
FACET_LIMIT = 60

_URL_FIELDS = (
    "detail_page",
    "funding_opportunity_url",
    "url",
    "primary_document_url",
)


def load_catalog(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    start = text.index("{")
    return json.loads(text[start:].strip().rstrip(";"))


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug or "other"


def best_url(record: dict) -> str:
    for field in _URL_FIELDS:
        value = record.get(field)
        if value:
            return str(value)
    return APP_URL


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d")
    except ValueError:
        return None


def entry_datetime(record: dict) -> datetime:
    dt = (
        parse_date(record.get("posted_date"))
        or parse_date(record.get("source_first_seen_date"))
        or parse_date(record.get("last_updated"))
    )
    if dt is None:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    return dt.replace(tzinfo=timezone.utc)


def catalog_datetime(catalog: dict) -> datetime:
    """Return a stable timestamp for the latest published catalog stage."""
    values = [
        catalog.get("generated_at"),
        catalog.get("detail_enrichment_generated_at"),
        catalog.get("document_evidence_generated_at"),
        ((catalog.get("diagnostics") or {}).get("additional_sources") or {}).get(
            "merged_at"
        ),
    ]
    parsed = []
    for value in values:
        if not value:
            continue
        try:
            parsed.append(
                datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(
                    timezone.utc
                )
            )
        except ValueError:
            continue
    return max(parsed) if parsed else datetime.now(timezone.utc)


def rfc3339(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def entry_id(record: dict) -> str:
    source = slugify(record.get("source") or "grants-gov")
    ident = record.get("opportunity_id") or record.get("opportunity_number") or best_url(record)
    return f"urn:funding-finder:{source}:{quote(str(ident), safe='')}"


def summarize(record: dict) -> str:
    bits = []
    if record.get("agency"):
        bits.append(str(record["agency"]))
    if record.get("close_date"):
        bits.append(f"Closes {record['close_date']}")
    elif record.get("status"):
        bits.append(str(record["status"]).title())
    description = (record.get("description") or "").strip()
    if description:
        bits.append(description[:400] + ("…" if len(description) > 400 else ""))
    return " — ".join(bits)


def sorted_recent(records: list[dict], limit: int) -> list[dict]:
    return sorted(records, key=entry_datetime, reverse=True)[:limit]


def build_atom(title: str, self_path: str, records: list[dict], updated: datetime) -> str:
    self_url = f"{FEEDS_BASE}/{self_path}"
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        f"  <title>{escape(title)}</title>",
        f"  <link href={quoteattr(self_url)} rel=\"self\"/>",
        f"  <link href={quoteattr(APP_URL)}/>",
        f"  <id>{escape(self_url)}</id>",
        f"  <updated>{rfc3339(updated)}</updated>",
        "  <generator>Funding Finder</generator>",
    ]
    for record in records:
        url = best_url(record)
        lines.append("  <entry>")
        lines.append(f"    <title>{escape(record.get('title') or 'Untitled opportunity')}</title>")
        lines.append(f"    <link href={quoteattr(url)}/>")
        lines.append(f"    <id>{escape(entry_id(record))}</id>")
        lines.append(f"    <updated>{rfc3339(entry_datetime(record))}</updated>")
        if record.get("agency"):
            lines.append(f"    <author><name>{escape(str(record['agency']))}</name></author>")
        for topic in (record.get("topic_areas") or [])[:8]:
            lines.append(f"    <category term={quoteattr(str(topic))}/>")
        lines.append(f"    <summary>{escape(summarize(record))}</summary>")
        lines.append("  </entry>")
    lines.append("</feed>")
    return "\n".join(lines) + "\n"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _facet_groups(records: list[dict], field: str) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for record in records:
        value = record.get(field)
        values = value if isinstance(value, list) else ([value] if value else [])
        for item in values:
            groups.setdefault(str(item), []).append(record)
    return groups


def build_feeds(
    catalog: dict,
    out_dir: Path,
    *,
    as_of=None,
) -> list[dict]:
    records, excluded = filter_current(
        catalog.get("opportunities") or [],
        as_of,
    )
    now = catalog_datetime(catalog)
    manifest: list[dict] = []
    generated_paths: set[Path] = set()

    def emit(title, rel_path, subset):
        destination = out_dir / rel_path
        _write(destination, build_atom(title, rel_path, sorted_recent(subset, FACET_LIMIT), now))
        generated_paths.add(destination)
        manifest.append({"title": title, "url": f"{FEEDS_BASE}/{rel_path}", "count": len(subset)})

    # All opportunities (larger limit).
    all_feed = out_dir / "all.xml"
    _write(all_feed, build_atom("Funding Finder — all new opportunities", "all.xml", sorted_recent(records, ALL_LIMIT), now))
    generated_paths.add(all_feed)
    manifest.append({"title": "All new opportunities", "url": f"{FEEDS_BASE}/all.xml", "count": len(records)})

    for value, subset in sorted(_facet_groups(records, "source_type").items()):
        emit(f"Funding Finder — {value}", f"source-type/{slugify(value)}.xml", subset)

    for value, subset in sorted(_facet_groups(records, "topic_areas").items()):
        emit(f"Funding Finder — {value}", f"topic/{slugify(value)}.xml", subset)

    changes_path = out_dir / "changes.xml"
    if changes_path.exists():
        manifest.append(
            {
                "title": "Opportunity changes",
                "url": f"{FEEDS_BASE}/changes.xml",
                "count": None,
            }
        )

    # Remove only obsolete files in the directories this generator owns.
    for managed_dir in (out_dir / "source-type", out_dir / "topic"):
        if managed_dir.exists():
            for path in managed_dir.glob("*.xml"):
                if path not in generated_paths:
                    path.unlink()

    _write(
        out_dir / "index.json",
        json.dumps(
            {
                "generated_at": rfc3339(now),
                "excluded_noncurrent": len(excluded),
                "feeds": manifest,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
    _write(out_dir / "index.html", _index_html(manifest, now))
    return manifest


def _index_html(manifest: list[dict], now: datetime) -> str:
    rows = "\n".join(
        f'      <li><a href="{escape(item["url"])}">{escape(item["title"])}</a> '
        + (
            f'<span class="count">({item["count"]})</span>'
            if item["count"] is not None
            else ""
        )
        + "</li>"
        for item in manifest
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Funding Finder — RSS feeds</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 42rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }}
    h1 {{ font-size: 1.4rem; }}
    .count {{ color: #667; font-size: .85em; }}
    li {{ margin: .25rem 0; }}
    code {{ background: #eef; padding: .1rem .3rem; border-radius: .2rem; }}
  </style>
</head>
<body>
  <h1>Funding Finder — subscribe by RSS</h1>
  <p>Copy any link below into your RSS/Atom reader to get new opportunities as
     they appear. No account or email needed. Updated {escape(rfc3339(now))}.</p>
  <p>For a small, consent-based pilot, the project also includes a
     <a href="{escape(ALERTS_DOC_URL)}">private-repository weekly email bundle</a>.
     Email subscriptions are not collected by this public site.</p>
  <ul>
{rows}
  </ul>
</body>
</html>
"""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate static Atom feeds from the catalog.")
    parser.add_argument("--catalog", default="data/opportunities.js")
    parser.add_argument("--out", default="feeds")
    args = parser.parse_args(argv)

    catalog = load_catalog(Path(args.catalog))
    manifest = build_feeds(catalog, Path(args.out))
    print(f"Wrote {len(manifest)} feeds to {args.out}/ (all.xml + {len(manifest) - 1} facet feeds).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
