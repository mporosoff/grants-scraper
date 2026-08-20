#!/usr/bin/env python3
"""One-time P9 evidence-cache pruning with a frozen, reviewable report."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile

from scripts.extract_document_evidence import (
    DEFAULT_CACHE,
    DEFAULT_CATALOG,
    prune_cache_to_catalog,
    read_cache,
    read_catalog,
    source_for_record,
    write_cache,
)


DEFAULT_REPORT = Path("evaluation/p9_cache_hygiene.json")
AS_OF = "2026-08-20"
EXPECTED_STALE = 213

# Live recheck performed at the P9.0 gate. The first twelve URLs were present
# in the current Grants.gov detail attachment list. NSF 352454 publishes no
# attachment today; its official URL resolves to the current canonical page.
ORPHAN_DISPOSITIONS = {
    "362544": "current_grants_detail_lists_cached_authoritative_attachment",
    "362069": "current_grants_detail_lists_cached_authoritative_attachment",
    "362068": "current_grants_detail_lists_cached_authoritative_attachment",
    "362067": "current_grants_detail_lists_cached_authoritative_attachment",
    "362070": "current_grants_detail_lists_cached_authoritative_attachment",
    "363404": "current_grants_detail_lists_cached_authoritative_attachment",
    "362099": "current_grants_detail_lists_cached_authoritative_attachment",
    "362370": "current_grants_detail_lists_cached_authoritative_attachment",
    "362962": "current_grants_detail_lists_cached_authoritative_attachment",
    "363530": "current_grants_detail_lists_cached_authoritative_attachment",
    "363526": "current_grants_detail_lists_cached_authoritative_attachment",
    "361822": "current_grants_detail_lists_cached_authoritative_attachment",
    "352454": "current_official_nsf_url_resolves_to_canonical_solicitation",
}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(payload, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=f".{path.stem}-", suffix=".tmp", delete=False,
        ) as output:
            temporary = Path(output.name)
            json.dump(payload, output, ensure_ascii=False, sort_keys=True, indent=2)
            output.write("\n")
        temporary.replace(path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    catalog = read_catalog(args.catalog)
    cache = read_cache(args.cache)
    records = catalog.get("opportunities") or []
    by_id = {
        str(record.get("opportunity_id") or record.get("opportunity_number")): record
        for record in records
    }
    cached = cache.get("records") or {}
    stale_ids = sorted(set(cached) - set(by_id))
    orphan_ids = sorted(
        identifier
        for identifier, record in by_id.items()
        if identifier in cached and source_for_record(record) is None
    )
    if len(stale_ids) != EXPECTED_STALE:
        raise RuntimeError(
            f"expected the frozen {EXPECTED_STALE} stale entries, got {len(stale_ids)}"
        )
    if orphan_ids != sorted(ORPHAN_DISPOSITIONS):
        raise RuntimeError(
            "current orphan population differs from the adjudicated 13: "
            + repr(orphan_ids)
        )

    input_hash = sha256(args.cache)
    orphan_report = []
    for identifier in orphan_ids:
        entry = cached[identifier]
        document = entry.get("document") or {}
        orphan_report.append({
            "opportunity_id": identifier,
            "opportunity_number": by_id[identifier].get("opportunity_number"),
            "disposition": "retain",
            "justification": ORPHAN_DISPOSITIONS[identifier],
            "document_url": document.get("url"),
            "document_sha256": document.get("sha256"),
        })

    if not args.apply:
        print(json.dumps({
            "stale_count": len(stale_ids),
            "orphan_count": len(orphan_ids),
        }, sort_keys=True))
        return 0

    removed = prune_cache_to_catalog(cache, catalog)
    if removed != stale_ids:
        raise RuntimeError("prune result differs from frozen stale population")
    write_cache(cache, args.cache)
    report = {
        "schema_version": 1,
        "as_of": AS_OF,
        "catalog_sha256": sha256(args.catalog),
        "evidence_cache_input_sha256": input_hash,
        "evidence_cache_output_sha256": sha256(args.cache),
        "catalog_record_count": len(by_id),
        "cache_record_count_before": len(cached),
        "cache_record_count_after": len(cache.get("records") or {}),
        "stale_pruned_count": len(stale_ids),
        "stale_pruned_ids": stale_ids,
        "orphan_rechecked_count": len(orphan_report),
        "orphan_resolutions": orphan_report,
        "attachment_truth_rule": (
            "Current Grants.gov detail attachment lists, never cached attachment_count, "
            "govern attachment reachability for records touched by P9."
        ),
    }
    atomic_json(report, args.report)
    print(json.dumps({
        "stale_pruned": len(stale_ids),
        "orphans_retained_with_justification": len(orphan_report),
        "remaining_cache_records": len(cache.get("records") or {}),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
