#!/usr/bin/env python3
"""Freeze and run P9's one-time current-parent subtopic campaign.

This is intentionally separate from the nightly evidence refresh. It walks the
frozen current-parent population once, so BUG-0's two independent nightly
budgets cannot truncate or misreport the first cache.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path
import tempfile
import time

from scripts import subtopic_records, subtopic_sources
from scripts.currentness import filter_current
from scripts.extract_document_evidence import (
    DEFAULT_CACHE as DEFAULT_EVIDENCE_CACHE,
    DEFAULT_CATALOG,
    download_document,
    extract_containers,
    read_cache as read_evidence_cache,
    read_catalog,
    source_for_record,
    subtopic_fields,
)


AS_OF = "2026-08-20"
FRAME_SCHEMA_VERSION = 1
DEFAULT_FRAME = Path("evaluation/p9_backfill_frame.json")
DEFAULT_RESULTS = Path("evaluation/p9_backfill_results.json")
MIN_CURRENT_ARPA_H_PARENTS = 6
CAMPAIGN_IMPLEMENTATION = (
    Path("scripts/build_subtopics.py"),
    Path("scripts/subtopic_records.py"),
    Path("scripts/subtopic_fields.py"),
    Path("scripts/subtopic_referenced.py"),
    Path("scripts/subtopic_sources.py"),
    Path("scripts/subtopic_segmentation.py"),
    Path("scripts/subtopic_structured.py"),
)


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def implementation_sha256(paths=CAMPAIGN_IMPLEMENTATION):
    digest = hashlib.sha256()
    for path in sorted(map(Path, paths), key=lambda item: item.as_posix()):
        digest.update(path.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


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


def parent_id(record):
    return str(record.get("opportunity_id") or record.get("opportunity_number") or "")


def validate_parent_source_surface(catalog, *, as_of=AS_OF):
    """The first cache must follow P9.0's newly admitted parent sources."""
    current, _excluded = filter_current(
        catalog.get("opportunities") or [], date.fromisoformat(as_of)
    )
    counts = Counter(str(record.get("source") or "") for record in current)
    if counts["ARPA-H"] < MIN_CURRENT_ARPA_H_PARENTS:
        return [
            "arpa_h_current_parent_floor:"
            f"{counts['ARPA-H']}<{MIN_CURRENT_ARPA_H_PARENTS}"
        ]
    return []


def frame_payload(catalog, evidence_cache, *, as_of=AS_OF):
    current, excluded = filter_current(
        catalog.get("opportunities") or [], date.fromisoformat(as_of)
    )
    cached_ids = set((evidence_cache.get("records") or {}))
    population = []
    for record in sorted(current, key=parent_id):
        source = source_for_record(record) or subtopic_sources.subtopic_only_primary(record)
        population.append({
            "opportunity_id": parent_id(record),
            "opportunity_number": record.get("opportunity_number"),
            "evidence_cached": parent_id(record) in cached_ids,
            "source_route": (source or {}).get("kind") or "current_detail_attachments",
            "source_url": (source or {}).get("url"),
        })
    return {
        "schema_version": FRAME_SCHEMA_VERSION,
        "as_of": as_of,
        "catalog_record_count": len(catalog.get("opportunities") or []),
        "current_parent_count": len(population),
        "excluded_parent_count": len(excluded),
        "excluded_reason_counts": dict(sorted(Counter(
            item["reason"] for item in excluded
        ).items())),
        "evidence_cache_record_count": len(cached_ids),
        "population": population,
    }


def _document_from(source, response):
    content = response.get("content") or b""
    return {
        "url": response.get("url") or source.get("url"),
        "name": source.get("name"),
        "content_type": response.get("content_type"),
        "sha256": hashlib.sha256(content).hexdigest() if content else None,
        "source_kind": source.get("kind"),
        "etag": response.get("etag"),
        "last_modified": response.get("last_modified"),
    }


def run_campaign(
    records,
    *,
    as_of=AS_OF,
    fetcher=download_document,
    container_extractor=extract_containers,
    field_builder=subtopic_fields,
    request_delay=0.05,
    progress=None,
    resume=None,
    checkpoint=None,
):
    resume = resume or {}
    cache = resume.get("cache") or subtopic_records.empty_cache()
    saved_metrics = resume.get("metrics") or {}
    metrics = {
        "attempted_parent_count": int(saved_metrics.get("attempted_parent_count") or 0),
        "top_level_fetch_failures": list(saved_metrics.get("top_level_fetch_failures") or []),
        "field_errors": list(saved_metrics.get("field_errors") or []),
        "cov4_offered": int(saved_metrics.get("cov4_offered") or 0),
        "cov4_classifier_calls": int(saved_metrics.get("cov4_classifier_calls") or 0),
        "cov4_classifier_errors": Counter(saved_metrics.get("cov4_classifier_errors") or {}),
        "structured_failure_reasons": Counter(
            saved_metrics.get("structured_failure_reasons") or {}
        ),
    }
    completed = {str(value) for value in resume.get("completed_parent_ids") or []}
    ordered = sorted(records, key=parent_id)
    for index, record in enumerate(ordered, start=1):
        identifier = parent_id(record)
        if identifier in completed:
            continue
        metrics["attempted_parent_count"] += 1
        source = source_for_record(record) or subtopic_sources.subtopic_only_primary(record)
        content = b""
        containers = []
        document = None
        if source and source.get("url"):
            try:
                response = fetcher(source["url"], {})
                content = response.get("content") or b""
                document = _document_from(source, response)
                containers, _extraction = container_extractor(
                    content,
                    document.get("content_type"),
                    document.get("name"),
                    document.get("url"),
                )
            except Exception as exc:  # one source may not abort 1,000 parents
                metrics["top_level_fetch_failures"].append({
                    "opportunity_id": identifier,
                    "error": type(exc).__name__,
                })
                document = {
                    "url": source.get("url"),
                    "name": source.get("name"),
                    "source_kind": source.get("kind"),
                }
        try:
            fields = field_builder(
                record,
                content,
                containers,
                document,
                f"{as_of}T00:00:00Z",
                True,
            )
        except Exception as exc:  # fail closed; preserve the exact parent
            fields = {"subtopics": [], "subtopic_reason": "campaign_field_error"}
            metrics["field_errors"].append({
                "opportunity_id": identifier,
                "error": type(exc).__name__,
            })

        cov4 = fields.get("subtopic_cov4") or {}
        metrics["cov4_offered"] += int(cov4.get("offered") or 0)
        metrics["cov4_classifier_calls"] += int(cov4.get("classifier_calls") or 0)
        metrics["cov4_classifier_errors"].update(cov4.get("classifier_errors") or {})
        if fields.get("subtopic_reason", "").startswith(("structured_", "native_")):
            metrics["structured_failure_reasons"][fields["subtopic_reason"]] += 1
        subtopic_records.upsert_parent(
            cache,
            identifier,
            fields.get("subtopics") or [],
            as_of=as_of,
            reason=fields.get("subtopic_reason") or (
                "no_children" if not fields.get("subtopics") else None
            ),
            method=fields.get("subtopic_method"),
        )
        completed.add(identifier)
        if checkpoint:
            checkpoint(cache, metrics, sorted(completed))
        if progress:
            progress(index, len(ordered), identifier, len(fields.get("subtopics") or []))
        if request_delay:
            time.sleep(request_delay)

    subtopic_records.retain_current_parents(cache, {parent_id(record) for record in ordered})
    metrics["cov4_classifier_errors"] = dict(sorted(
        metrics["cov4_classifier_errors"].items()
    ))
    metrics["structured_failure_reasons"] = dict(sorted(
        metrics["structured_failure_reasons"].items()
    ))
    return cache, metrics


def validate_cache(cache, current_parent_ids):
    anomalies = []
    current = {str(identifier) for identifier in current_parent_ids}
    for parent, entry in (cache.get("records") or {}).items():
        if parent not in current:
            anomalies.append(f"noncurrent_parent:{parent}")
        for child in entry.get("subtopics") or []:
            if child.get("parent_id") != parent:
                anomalies.append(f"wrong_parent:{child.get('subtopic_id')}")
            if child.get("child_type") != "subject":
                anomalies.append(f"wrong_type:{child.get('subtopic_id')}")
            if len(child.get("summary") or "") > 600:
                anomalies.append(f"long_summary:{child.get('subtopic_id')}")
            if len(child.get("subtopic_terms") or {}) > subtopic_records.MAX_TERMS:
                anomalies.append(f"term_overflow:{child.get('subtopic_id')}")
            if not child.get("source_document_hash"):
                anomalies.append(f"missing_hash:{child.get('subtopic_id')}")
    return anomalies


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--evidence-cache", type=Path, default=DEFAULT_EVIDENCE_CACHE)
    parser.add_argument("--frame", type=Path, default=DEFAULT_FRAME)
    parser.add_argument("--output", type=Path, default=subtopic_records.DEFAULT_CACHE)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument(
        "--checkpoint", type=Path,
        help="resumable scratch state (default: beside --output, ignored by git)",
    )
    parser.add_argument("--write-frame", action="store_true")
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--request-delay", type=float, default=0.05)
    args = parser.parse_args(argv)
    if args.write_frame == args.build:
        parser.error("choose exactly one of --write-frame or --build")
    return args


def main(argv=None):
    args = parse_args(argv)
    catalog = read_catalog(args.catalog)
    evidence = read_evidence_cache(args.evidence_cache)
    source_anomalies = validate_parent_source_surface(catalog)
    if source_anomalies:
        raise RuntimeError(
            "catalog does not contain P9.0's required current parent-source "
            "surface; rebuild it before freezing/running the first cache: "
            + ", ".join(source_anomalies)
        )
    frame = frame_payload(catalog, evidence)
    frame["catalog_sha256"] = file_sha256(args.catalog)
    frame["evidence_cache_sha256"] = file_sha256(args.evidence_cache)
    if args.write_frame:
        atomic_json(frame, args.frame)
        print(json.dumps({
            "current_parent_count": frame["current_parent_count"],
            "excluded_parent_count": frame["excluded_parent_count"],
        }, sort_keys=True))
        return 0

    frozen = json.loads(args.frame.read_text(encoding="utf-8"))
    if frozen != frame:
        raise RuntimeError("current catalog/evidence population differs from frozen frame")
    by_id = {parent_id(record): record for record in catalog["opportunities"]}
    current_records = [by_id[item["opportunity_id"]] for item in frozen["population"]]
    current_parent_ids = {parent_id(record) for record in current_records}
    checkpoint_path = args.checkpoint or args.output.with_suffix(".checkpoint.json")
    checkpoint_identity = {
        "schema_version": 1,
        "frame_catalog_sha256": frozen["catalog_sha256"],
        "frame_evidence_cache_sha256": frozen["evidence_cache_sha256"],
        "implementation_sha256": implementation_sha256(),
    }
    resume = None
    if checkpoint_path.exists():
        candidate = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        actual_identity = {key: candidate.get(key) for key in checkpoint_identity}
        if actual_identity != checkpoint_identity:
            raise RuntimeError(
                "P9 checkpoint does not match the frozen frame/current implementation; "
                "remove the stale scratch checkpoint before rebuilding"
            )
        resume = candidate

    def progress(index, total, identifier, children):
        if index == 1 or index % 25 == 0 or index == total:
            print(f"p9-backfill {index}/{total} parent={identifier} children={children}", flush=True)

    def save_checkpoint(cache, metrics, completed):
        atomic_json({
            **checkpoint_identity,
            "completed_parent_ids": completed,
            "cache": cache,
            "metrics": metrics,
        }, checkpoint_path)

    cache, campaign = run_campaign(
        current_records,
        request_delay=args.request_delay,
        progress=progress,
        resume=resume,
        checkpoint=save_checkpoint,
    )
    anomalies = validate_cache(cache, current_parent_ids)
    if anomalies:
        raise RuntimeError("sidecar validation failed: " + ", ".join(anomalies[:20]))
    metrics = subtopic_records.cache_metrics(cache)
    cache["generation"] = {
        "as_of": AS_OF,
        "frame_catalog_sha256": frozen["catalog_sha256"],
        "frame_evidence_cache_sha256": frozen["evidence_cache_sha256"],
        "attempted_parent_count": campaign["attempted_parent_count"],
        "top_level_fetch_failure_count": len(campaign["top_level_fetch_failures"]),
        "field_error_count": len(campaign["field_errors"]),
        "cov4_offered": campaign["cov4_offered"],
        "cov4_classifier_calls": campaign["cov4_classifier_calls"],
        "cov4_classifier_errors": campaign["cov4_classifier_errors"],
    }
    subtopic_records.write_cache(cache, args.output)
    payload = subtopic_records.read_cache(args.output)
    results = {
        "schema_version": 1,
        "as_of": AS_OF,
        "frame_catalog_sha256": frozen["catalog_sha256"],
        "frame_evidence_cache_sha256": frozen["evidence_cache_sha256"],
        "sidecar_sha256": file_sha256(args.output),
        "campaign": campaign,
        "cache_metrics": metrics,
        "sidecar_parent_count": payload.get("parent_count"),
        "sidecar_record_count": payload.get("record_count"),
        "sidecar_searchable_record_count": payload.get("searchable_record_count"),
        "validation_anomalies": anomalies,
    }
    atomic_json(results, args.results)
    if checkpoint_path.exists():
        checkpoint_path.unlink()
    print(json.dumps({
        "parents": results["sidecar_parent_count"],
        "children": results["sidecar_record_count"],
        "searchable": results["sidecar_searchable_record_count"],
        "model_calls": campaign["cov4_classifier_calls"],
        "model_errors": campaign["cov4_classifier_errors"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
