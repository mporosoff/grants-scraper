"""Aggregate privacy-safe Phase 3 deployment-review exports.

Reviewers use the site's single "Send review" action. On mobile it opens the
native share sheet with the JSON file attached; on desktop it downloads the
file and opens an addressed email. The project owner saves returned files under
``evaluation/inbox/`` and runs this module to create a readable summary, a
machine-readable summary, and a row-level CSV. Both folders are gitignored.
"""

import argparse
from collections import Counter
import csv
import json
from pathlib import Path


SCHEMA_VERSION = 1
EXPECTED_KIND = "funding_finder_phase3_deployment_review"
DEFAULT_INPUT = Path("evaluation/inbox")
DEFAULT_OUTPUT = Path("evaluation/reports")


def iter_json_files(inputs):
    seen = set()
    for raw in inputs:
        path = Path(raw)
        candidates = sorted(path.rglob("*.json")) if path.is_dir() else [path]
        for candidate in candidates:
            resolved = candidate.resolve()
            if candidate.suffix.casefold() != ".json" or resolved in seen:
                continue
            seen.add(resolved)
            yield candidate


def read_export(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError(
            f"{path} uses unsupported review schema "
            f"{payload.get('schema_version')!r}."
        )
    if payload.get("kind") != EXPECTED_KIND:
        raise RuntimeError(f"{path} is not a Phase 3 deployment-review export.")
    review = payload.get("review") or {}
    if not review.get("review_id"):
        raise RuntimeError(f"{path} is missing a review identifier.")
    return payload


def load_exports(inputs):
    latest = {}
    failures = []
    for path in iter_json_files(inputs):
        try:
            payload = read_export(path)
        except Exception as exc:  # noqa: BLE001 - report every bad handoff
            failures.append({"file": str(path), "error": str(exc)})
            continue
        review_id = payload["review"]["review_id"]
        exported_at = payload.get("exported_at") or ""
        current = latest.get(review_id)
        if not current or exported_at >= (current.get("exported_at") or ""):
            payload["_source_file"] = str(path)
            latest[review_id] = payload
    return list(latest.values()), failures


def aggregate(exports, failures=None):
    failures = failures or []
    source_statuses = Counter()
    source_fields = Counter()
    failed_checks = Counter()
    match_labels = Counter()
    match_reasons = Counter()
    usage = Counter()
    rows = []
    overall_notes = []

    for payload in exports:
        review = payload.get("review") or {}
        review_id = review.get("review_id")
        participant_code = review.get("participant_code") or ""
        note = str(review.get("overall_note") or "").strip()
        if note:
            overall_notes.append(
                {
                    "review_id": review_id,
                    "participant_code": participant_code,
                    "note": note,
                }
            )
        for name, value in (review.get("deployment_checks") or {}).items():
            if value == "no":
                failed_checks[name] += 1
        for name, value in (review.get("usage") or {}).items():
            try:
                usage[name] += int(value or 0)
            except (TypeError, ValueError):
                continue
        for source_review in review.get("source_reviews") or []:
            status = source_review.get("status") or "unknown"
            field = source_review.get("field") or "overall"
            source_statuses[status] += 1
            source_fields[field] += 1
            rows.append(
                {
                    "review_id": review_id,
                    "participant_code": participant_code,
                    "exported_at": payload.get("exported_at") or "",
                    "opportunity_id": source_review.get("opportunity_id") or "",
                    "opportunity_number": source_review.get(
                        "opportunity_number"
                    )
                    or "",
                    "title": source_review.get("title") or "",
                    "agency": source_review.get("agency") or "",
                    "status": status,
                    "field": field,
                    "note": source_review.get("note") or "",
                    "document_url": source_review.get("document_url") or "",
                    "document_sha256": source_review.get(
                        "document_sha256"
                    )
                    or "",
                    "document_version": source_review.get(
                        "document_version"
                    )
                    or "",
                    "evidence_ids": ";".join(
                        source_review.get("evidence_ids") or []
                    ),
                    "catalog_generated_at": source_review.get(
                        "catalog_generated_at"
                    )
                    or "",
                }
            )
        for match in payload.get("match_feedback") or []:
            if match.get("label"):
                match_labels[match["label"]] += 1
            if match.get("reason"):
                match_reasons[match["reason"]] += 1

    verified = source_statuses["accurate"] + source_statuses["incorrect"]
    accuracy_rate = (
        source_statuses["accurate"] / verified if verified else None
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "review_count": len(exports),
        "source_review_count": len(rows),
        "source_status_counts": dict(sorted(source_statuses.items())),
        "source_field_counts": dict(sorted(source_fields.items())),
        "verified_source_accuracy_rate": accuracy_rate,
        "failed_deployment_checks": dict(sorted(failed_checks.items())),
        "match_label_counts": dict(sorted(match_labels.items())),
        "match_reason_counts": dict(sorted(match_reasons.items())),
        "usage_totals": dict(sorted(usage.items())),
        "overall_notes": overall_notes,
        "invalid_files": failures,
        "source_rows": rows,
    }


def percentage(value):
    return "not measured" if value is None else f"{value * 100:.1f}%"


def markdown_report(summary):
    lines = [
        "# Funding Finder Phase 3 deployment review",
        "",
        f"- Review packages: {summary['review_count']}",
        f"- Source facts reviewed: {summary['source_review_count']}",
        (
            "- Verified source-fact accuracy: "
            f"{percentage(summary['verified_source_accuracy_rate'])}"
        ),
        f"- Invalid files skipped: {len(summary['invalid_files'])}",
        "",
        "## Source-verification outcomes",
        "",
    ]
    if summary["source_status_counts"]:
        lines.extend(
            f"- {name.replace('_', ' ').title()}: {count}"
            for name, count in summary["source_status_counts"].items()
        )
    else:
        lines.append("- No source reviews were returned.")

    lines.extend(["", "## Fields reviewed", ""])
    if summary["source_field_counts"]:
        lines.extend(
            f"- {name.replace('_', ' ').title()}: {count}"
            for name, count in summary["source_field_counts"].items()
        )
    else:
        lines.append("- No field-level reviews were returned.")

    lines.extend(["", "## Deployment checks needing attention", ""])
    if summary["failed_deployment_checks"]:
        lines.extend(
            f"- {name.replace('_', ' ').title()}: {count}"
            for name, count in summary["failed_deployment_checks"].items()
        )
    else:
        lines.append("- No check was marked as failed.")

    lines.extend(["", "## Match feedback included", ""])
    if summary["match_label_counts"]:
        lines.extend(
            f"- {name.replace('_', ' ').title()}: {count}"
            for name, count in summary["match_label_counts"].items()
        )
    else:
        lines.append("- No match ratings were included.")

    lines.extend(["", "## Usage totals (device-local counters)", ""])
    if summary["usage_totals"]:
        lines.extend(
            f"- {name.replace('_', ' ').title()}: {count}"
            for name, count in summary["usage_totals"].items()
            if count
        )
        if not any(summary["usage_totals"].values()):
            lines.append("- No counted actions were recorded.")
    else:
        lines.append("- No counted actions were recorded.")

    lines.extend(["", "## Reviewer notes", ""])
    if summary["overall_notes"]:
        for entry in summary["overall_notes"]:
            reviewer = entry["participant_code"] or entry["review_id"]
            lines.append(f"- **{reviewer}:** {entry['note']}")
    else:
        lines.append("- No overall notes were returned.")

    if summary["invalid_files"]:
        lines.extend(["", "## Files needing manual review", ""])
        lines.extend(
            f"- `{item['file']}`: {item['error']}"
            for item in summary["invalid_files"]
        )
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(summary, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / "phase3-review-summary.md"
    json_path = output_dir / "phase3-review-summary.json"
    csv_path = output_dir / "phase3-source-reviews.csv"

    markdown_path.write_text(
        markdown_report(summary),
        encoding="utf-8",
        newline="\n",
    )
    machine_summary = {
        key: value
        for key, value in summary.items()
        if key != "source_rows"
    }
    json_path.write_text(
        f"{json.dumps(machine_summary, indent=2, ensure_ascii=False)}\n",
        encoding="utf-8",
        newline="\n",
    )
    fieldnames = [
        "review_id",
        "participant_code",
        "exported_at",
        "opportunity_id",
        "opportunity_number",
        "title",
        "agency",
        "status",
        "field",
        "note",
        "document_url",
        "document_sha256",
        "document_version",
        "evidence_ids",
        "catalog_generated_at",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary["source_rows"])
    return markdown_path, json_path, csv_path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Aggregate returned Phase 3 deployment-review files."
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        default=[DEFAULT_INPUT],
        help="JSON files or directories (default: evaluation/inbox).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Private report directory (default: evaluation/reports).",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    exports, failures = load_exports(args.inputs)
    if not exports:
        details = (
            f" {len(failures)} invalid file(s) were found."
            if failures
            else ""
        )
        raise SystemExit(
            "No valid Phase 3 review exports were found." + details
        )
    summary = aggregate(exports, failures)
    paths = write_outputs(summary, args.output_dir)
    print(
        f"Aggregated {summary['review_count']} review package(s) and "
        f"{summary['source_review_count']} source review(s)."
    )
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
