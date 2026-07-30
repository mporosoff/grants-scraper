"""Regenerate documentation statistics from the published browser catalog."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
import textwrap
from typing import Any

from scripts.currentness import filter_current

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PREFIX = "globalThis.GRANT_CATALOG="
CATALOG_SCRIPT_RE = re.compile(
    r'<script src="\./data/opportunities\.js(?:\?v=[^"]+)?"></script>'
)


def load_catalog(path: Path) -> dict[str, Any]:
    asset = path.read_text(encoding="utf-8")
    if CATALOG_PREFIX not in asset:
        raise ValueError(f"{path} does not contain {CATALOG_PREFIX!r}")
    payload = asset.split(CATALOG_PREFIX, 1)[1].strip().removesuffix(";")
    catalog = json.loads(payload)
    if catalog.get("record_count") != len(catalog.get("opportunities", [])):
        raise ValueError("catalog record_count does not match opportunities")
    return catalog


def catalog_stats(catalog: dict[str, Any]) -> dict[str, Any]:
    generated = datetime.fromisoformat(
        catalog["generated_at"].replace("Z", "+00:00")
    ).date()
    records, excluded = filter_current(catalog["opportunities"], generated)
    routes = Counter(
        "direct"
        if record.get("primary_document_url")
        else "agency"
        if record.get("funding_opportunity_url")
        else "grants"
        for record in records
    )
    confidence = Counter(
        record.get("primary_document_confidence")
        for record in records
        if record.get("primary_document_url")
    )
    per_award = sum(
        record.get("award_floor") is not None
        or record.get("award_ceiling") is not None
        for record in records
    )
    any_amount = sum(
        record.get("award_floor") is not None
        or record.get("award_ceiling") is not None
        or record.get("total_program_funding") is not None
        for record in records
    )
    deadline_context = sum(
        any(deadline.get("time") or deadline.get("timezone")
            for deadline in record.get("deadlines", []))
        for record in records
    )
    preliminary = sum(bool(record.get("has_preliminary_stage"))
                      for record in records)
    narrative_preliminary = sum(
        bool(record.get("preliminary_deadline")) for record in records
    )
    past_deadlines = sum(
        bool(record.get("close_date"))
        and date.fromisoformat(record["close_date"]) < generated
        for record in records
    )
    diagnostics = catalog.get("diagnostics", {})
    details = diagnostics.get("detail_enrichment", {})
    source_counts = Counter(
        record.get("source") or "Source not listed" for record in records
    )
    stats = {
        "generated": generated,
        "record_count": len(records),
        "posted": sum(record.get("status") == "posted" for record in records),
        "forecasted": sum(
            record.get("status") == "forecasted" for record in records
        ),
        "excluded_noncurrent": len(excluded),
        "direct": routes["direct"],
        "direct_high": confidence["high"],
        "direct_medium": confidence["medium"],
        "agency_route": routes["agency"],
        "grants_route": routes["grants"],
        "agency_url_total": sum(
            bool(record.get("funding_opportunity_url")) for record in records
        ),
        "deadline_context": deadline_context,
        "preliminary": preliminary,
        "narrative_preliminary": narrative_preliminary,
        "per_award": per_award,
        "any_amount": any_amount,
        "past_deadlines": past_deadlines,
        "deadline_conflicts": details.get("deadline_conflict_count", 0),
        "source_counts": dict(sorted(source_counts.items())),
        "non_grants_count": sum(
            count for source, count in source_counts.items()
            if source != "Grants.gov"
        ),
    }
    if sum(routes.values()) != stats["record_count"]:
        raise ValueError("primary source route counts do not cover the catalog")
    return stats


def catalog_asset_version(catalog: dict[str, Any]) -> str:
    """Build a cache-busting token from the latest completed catalog stage."""
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
            timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            parsed.append(timestamp.astimezone(timezone.utc))
        except ValueError:
            continue
    if not parsed:
        raise ValueError("catalog has no valid generated timestamp")
    latest = max(parsed)
    return latest.strftime("catalog-%Y%m%dT%H%M%SZ")


def update_catalog_asset_reference(html: str, catalog: dict[str, Any]) -> str:
    matches = CATALOG_SCRIPT_RE.findall(html)
    if len(matches) != 1:
        raise ValueError("expected exactly one opportunity catalog script reference")
    replacement = (
        '<script src="./data/opportunities.js?v='
        f'{catalog_asset_version(catalog)}"></script>'
    )
    return CATALOG_SCRIPT_RE.sub(replacement, html)


def format_date(value: date) -> str:
    return f"{value.strftime('%B')} {value.day}, {value.year}"


def percent(value: int, total: int) -> str:
    return f"{value / total * 100:.1f}%"


def count_label(value: int) -> str:
    return "zero" if value == 0 else f"{value:,}"


def paragraph(value: str) -> str:
    return textwrap.fill(value, width=88)


def bullet(value: str) -> str:
    return textwrap.fill(
        f"- {value}", width=88, subsequent_indent="  "
    )


def readme_block(stats: dict[str, Any]) -> str:
    sources = ", ".join(
        f"{source} ({count:,})"
        for source, count in stats["source_counts"].items()
    )
    return paragraph(
        "This replaces the former 48-record Chemical and Sustainability "
        f"Engineering feed. The {format_date(stats['generated'])} build "
        f"contains {stats['record_count']:,} current funding opportunities "
        f"({stats['posted']:,} posted and {stats['forecasted']:,} forecasted) "
        f"from {sources}, with no deadline before the catalog date. It provides a direct "
        f"official announcement for {stats['direct']:,} records, an "
        f"official source-page route for another {stats['agency_route']:,}, and the "
        "official Grants.gov record for the remaining "
        f"{stats['grants_route']:,}. Across all route types, "
        f"{stats['agency_url_total']:,} records also contain an official source "
        "URL."
    )


def project_summary_block(stats: dict[str, Any]) -> str:
    sources = ", ".join(
        f"{source} ({count:,})"
        for source, count in stats["source_counts"].items()
    )
    return paragraph(
        f"The {format_date(stats['generated'])} build contains "
        f"{stats['record_count']:,} open or current forecasted funding "
        f"opportunities ({stats['posted']:,} posted and "
        f"{stats['forecasted']:,} forecasted) rather than the former 48-record "
        "engineering shortlist. It contains no record with a deadline before "
        f"the catalog date. Current published sources are {sources}; additional "
        "sources are enabled only after a sustainable public ingestion path and "
        "health bounds are verified."
    )


def project_evidence_block(stats: dict[str, Any]) -> str:
    record_count = stats["record_count"]
    heading = paragraph(
        f"The {format_date(stats['generated'])} catalog contains "
        f"{record_count:,} current posted or forecasted opportunities:"
    )
    bullets = [
        bullet(
            f"{stats['direct']:,} have a defensible direct announcement "
            f"attachment ({stats['direct_high']:,} high confidence, "
            f"{stats['direct_medium']:,} medium confidence);"
        ),
        bullet(
            f"another {stats['agency_route']:,} use an official source page "
            "as their primary route;"
        ),
        bullet(
            f"the remaining {stats['grants_route']:,} use the official "
            "Grants.gov record as their primary route;"
        ),
        bullet(
            f"{stats['agency_url_total']:,} contain an agency notice URL "
            "across all route types;"
        ),
        bullet(
            f"{stats['deadline_context']:,} preserve an official deadline time "
            "or timezone;"
        ),
        bullet(
            f"{stats['preliminary']:,} carry a preliminary-stage signal, "
            f"including {stats['narrative_preliminary']:,} narrative dates "
            "visibly marked for verification;"
        ),
        bullet(
            f"{stats['per_award']:,} "
            f"({percent(stats['per_award'], record_count)}) have an official "
            "per-award floor or ceiling;"
        ),
        bullet(
            f"{stats['any_amount']:,} "
            f"({percent(stats['any_amount'], record_count)}) have at least one "
            "structured funding amount; and"
        ),
        bullet(
            f"{count_label(stats['past_deadlines'])} have a past structured "
            f"close date and {count_label(stats['deadline_conflicts'])} have a "
            "detected XML/detail-API deadline conflict in this build."
        ),
    ]
    return f"{heading}\n\n" + "\n".join(bullets)


def replace_block(text: str, marker: str, content: str) -> str:
    start = f"<!-- {marker}:start -->"
    end = f"<!-- {marker}:end -->"
    if text.count(start) != 1 or text.count(end) != 1:
        raise ValueError(f"expected exactly one {marker!r} marker pair")
    before, remainder = text.split(start, 1)
    _, after = remainder.split(end, 1)
    return f"{before}{start}\n{content}\n{end}{after}"


def render_docs(
    readme: str, project: str, stats: dict[str, Any]
) -> tuple[str, str]:
    readme = replace_block(readme, "catalog-stats", readme_block(stats))
    project = replace_block(
        project, "catalog-summary", project_summary_block(stats)
    )
    project = replace_block(
        project, "catalog-evidence", project_evidence_block(stats)
    )
    return readme, project


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog",
        type=Path,
        default=REPOSITORY_ROOT / "data" / "opportunities.js",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit nonzero instead of writing when documentation is stale.",
    )
    args = parser.parse_args()
    readme_path = REPOSITORY_ROOT / "README.md"
    project_path = REPOSITORY_ROOT / "PROJECT.md"
    explorer_path = REPOSITORY_ROOT / "match_explorer.html"
    catalog = load_catalog(args.catalog)
    stats = catalog_stats(catalog)
    current_readme = readme_path.read_text(encoding="utf-8")
    current_project = project_path.read_text(encoding="utf-8")
    current_explorer = explorer_path.read_text(encoding="utf-8")
    next_readme, next_project = render_docs(
        current_readme, current_project, stats
    )
    next_explorer = update_catalog_asset_reference(
        current_explorer, catalog
    )
    changed = []
    if current_readme != next_readme:
        changed.append(readme_path)
    if current_project != next_project:
        changed.append(project_path)
    if current_explorer != next_explorer:
        changed.append(explorer_path)
    if args.check and changed:
        print("Catalog documentation is stale:")
        for path in changed:
            print(f"- {path.relative_to(REPOSITORY_ROOT)}")
        return 1
    if not args.check:
        readme_path.write_text(next_readme, encoding="utf-8", newline="\n")
        project_path.write_text(next_project, encoding="utf-8", newline="\n")
        explorer_path.write_text(
            next_explorer, encoding="utf-8", newline="\n"
        )
    print(
        f"Catalog documentation is current for {stats['record_count']:,} "
        f"records ({format_date(stats['generated'])})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
