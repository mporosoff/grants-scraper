"""Run P7's final production-only gate on the frozen 33 negative documents.

The source frame is the one frozen before P7.4a.  This runner verifies each
document hash before handing its bytes to the current production segmenter,
record builder, Cov4 gate, and Cov6 publication predicate.  It does not import
or run the measurement-only Fm2 candidate parser.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import subtopic_cov4 as cov4                         # noqa: E402
from scripts import subtopic_records as records                   # noqa: E402
from scripts import subtopic_segmentation as segmentation         # noqa: E402
from scripts.extract_document_evidence import (                   # noqa: E402
    download_document,
    extract_containers,
)
from scripts.sources.merge import load_catalog                    # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
FRAME = ROOT / "evaluation" / "fm2_gate_frame.json"
OUT = ROOT / "evaluation" / "p7_closeout.json"
EVIDENCE = ROOT / "data" / "document_evidence.json"
CATALOG = ROOT / "data" / "opportunities.js"
AS_OF = "2026-08-20"


def load_inputs():
    frame = json.loads(FRAME.read_text(encoding="utf-8"))
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))["records"]
    catalog = {
        str(row["opportunity_id"]): row
        for row in load_catalog(CATALOG)["opportunities"]
    }
    return frame, evidence, catalog


def resolve_document(record_id, frame, evidence):
    override = frame.get("source_overrides", {}).get(record_id)
    return dict(override or evidence[record_id]["document"])


def resolve_parent(record_id, frame, catalog):
    return catalog.get(record_id) or frame["archived_parents"][record_id]


def source_result(record_id, document, response):
    content = response.get("content") or b""
    if not content:
        return None, {
            "opportunity_id": record_id,
            "status": "source_error",
            "detail": f"no content (status {response.get('status_code')})",
            "document": document,
        }
    received = hashlib.sha256(content).hexdigest()
    if received != document["sha256"]:
        return None, {
            "opportunity_id": record_id,
            "status": "source_hash_drift",
            "expected_sha256": document["sha256"],
            "received_sha256": received,
            "document": document,
        }
    return content, None


def measure_document(record_id, frame, evidence, catalog, *, session=None):
    document = resolve_document(record_id, frame, evidence)
    parent = resolve_parent(record_id, frame, catalog)
    response = download_document(document["url"])
    content, failure = source_result(record_id, document, response)
    if failure:
        return failure

    try:
        containers, extraction = extract_containers(
            content,
            document.get("content_type"),
            document.get("name"),
            document.get("url"),
        )
    except RuntimeError as exc:
        if str(exc).startswith("Unsupported official-document content type:"):
            return {
                "opportunity_id": record_id,
                "status": "hash_verified_unsupported_format",
                "detail": str(exc),
                "document": document,
                "segmentation": None,
                "structural_titles": [],
                "cov4_titles": [],
                "publication": [],
            }
        raise

    result = segmentation.segment_document(
        parent,
        content,
        containers,
        document,
        parent_deadline=parent.get("close_date"),
    )
    built = records.build_records(
        parent,
        result,
        document=document,
        as_of=AS_OF,
        provenance=records.INFERRED,
    )
    kept, diagnostics = cov4.apply_gate(
        parent, built, document, session=session
    )
    publication = []
    for record in kept:
        state, reason = records.publication_eligibility(record)
        publication.append({
            "subtopic_id": record["subtopic_id"],
            "title": record["title"],
            "state": state,
            "reason": reason,
        })
    return {
        "opportunity_id": record_id,
        "status": "hash_verified_scanned",
        "document": document,
        "extraction": extraction,
        "segmentation": {
            "method": result.method,
            "family": result.family,
            "confidence": result.confidence,
            "reason": result.reason,
            "layers_attempted": list(result.layers_attempted),
        },
        "structural_titles": [record["title"] for record in built],
        "cov4_titles": [record["title"] for record in kept],
        "cov4_diagnostics": diagnostics,
        "publication": publication,
    }


def aggregate(rows):
    scanned = [row for row in rows if row["status"] == "hash_verified_scanned"]
    unsupported = [
        row for row in rows
        if row["status"] == "hash_verified_unsupported_format"
    ]
    drift = [row for row in rows if row["status"] == "source_hash_drift"]
    source_errors = [row for row in rows if row["status"] == "source_error"]
    processing_errors = [row for row in rows if row["status"] == "processing_error"]
    publication = [item for row in rows for item in row.get("publication", [])]
    diagnostics = [
        row.get("cov4_diagnostics", {}) for row in scanned
    ]
    return {
        "documents_attempted": len(rows),
        "documents_hash_verified": len(scanned) + len(unsupported),
        "documents_scanned_by_production": len(scanned),
        "unsupported_formats": len(unsupported),
        "source_hash_drift": len(drift),
        "source_errors": len(source_errors),
        "processing_errors": len(processing_errors),
        "structural_candidate_sets": sum(
            bool(row.get("structural_titles")) for row in scanned
        ),
        "structural_false_positive_children": sum(
            len(row.get("structural_titles", [])) for row in scanned
        ),
        "cov4_false_positive_children": sum(
            len(row.get("cov4_titles", [])) for row in scanned
        ),
        "review_children": sum(
            item["state"] == records.REVIEW for item in publication
        ),
        "publishable_children": sum(
            item["state"] == records.PUBLISHABLE for item in publication
        ),
        "publishable_titles": [
            item["title"] for item in publication
            if item["state"] == records.PUBLISHABLE
        ],
        "classifier_calls": sum(row.get("classifier_calls", 0)
                                for row in diagnostics),
        "classifier_errors": sum(
            sum(row.get("classifier_errors", {}).values())
            for row in diagnostics
        ),
        "drift_ids": [row["opportunity_id"] for row in drift],
        "source_error_ids": [row["opportunity_id"] for row in source_errors],
        "processing_error_ids": [
            row["opportunity_id"] for row in processing_errors
        ],
        "structural_false_positive_ids": [
            row["opportunity_id"] for row in scanned
            if row.get("structural_titles")
        ],
    }


def run(out_path=OUT):
    frame, evidence, catalog = load_inputs()
    record_ids = frame["populations"]["category_a_negative_ids"]
    import requests
    session = requests.Session()
    rows = []
    for record_id in record_ids:
        try:
            rows.append(measure_document(
                record_id, frame, evidence, catalog, session=session
            ))
        except Exception as exc:  # an isolated document failure is gate evidence
            rows.append({
                "opportunity_id": record_id,
                "status": "processing_error",
                "detail": f"{type(exc).__name__}: {str(exc)[:240]}",
            })
    result = {
        "schema_version": 1,
        "purpose": "P7 final production-only gate on the frozen category-(a) negatives",
        "frame": str(FRAME.relative_to(ROOT)).replace("\\", "/"),
        "frame_sha256": hashlib.sha256(FRAME.read_bytes()).hexdigest(),
        "production_cov4_model": cov4.MODEL,
        "production_cov4_repeats": cov4.REPEATS,
        "documents": rows,
    }
    result["summary"] = aggregate(rows)
    Path(out_path).write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    summary = result["summary"]
    print(f"documents attempted: {summary['documents_attempted']}")
    print(f"documents hash-verified: {summary['documents_hash_verified']}")
    print(f"source hash drift: {summary['source_hash_drift']}")
    print(f"processing errors: {summary['processing_errors']}")
    print("production structural false-positive children: "
          f"{summary['structural_false_positive_children']}")
    print(f"publishable children: {summary['publishable_children']}")
    print(f"classifier errors: {summary['classifier_errors']}")
    return result


def main():
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
