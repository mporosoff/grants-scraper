"""P7.4a's measurement-only bare-numbered F1 gate instrument.

This file is deliberately outside production segmentation.  It proposes F1
candidates for the frozen frame in ``evaluation/fm2_gate_frame.json``, then
hands admitted spans to production's existing record builder, Cov4 gate, and
Cov6 publication predicate.  It does not add a family, layer, cache path, or
shipping behavior.

The candidate grammar and grouping rules were frozen with the frame before the
aggregate corpus or live classifier outcomes were read.  A failed precision or
recall result is evidence for the P7.4a decision, not an invitation to tune this
instrument in the same measurement.

Usage (after loading the User-scope API key into this PowerShell invocation)::

    python tools/run_fm2_gate.py
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
import zipfile

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
DEFAULT_FRAME = ROOT / "evaluation" / "fm2_gate_frame.json"
DEFAULT_OUT = ROOT / "evaluation" / "fm2_gate_results.json"
EVIDENCE = ROOT / "data" / "document_evidence.json"
CATALOG = ROOT / "data" / "opportunities.js"

# The complete first-pass F1 grammar.  No label word is admitted.  A counter is
# 1-60 and its delimiter is exactly `.`, `)`, `.)`, or a spaced dash.  Requiring
# whitespace after the delimiter keeps decimal section numbers (`1.2`) out.
F1_LINE = re.compile(
    r"^[ \t]*(?P<ordinal>[1-9]|[1-5]\d|60)"
    r"(?P<marker>\.\)|[.)]|[ \t]+[-–—])"
    r"[ \t]+(?P<title>\S[^\r\n]*)$",
    re.MULTILINE,
)
EXPLANATORY_DASH = re.compile(r"^(?P<title>.+?)\s+[-–—]\s+\S.*$")
WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
AS_OF = "2026-08-20"


def normalise_title(value: str) -> str:
    """Stable comparison only; the source title itself is never rewritten."""
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^a-z0-9]+", " ", value.casefold())
    return " ".join(value.split())


def clean_title(raw: str) -> str:
    """Remove only a same-line explanatory dash clause.

    This is the 355150 requirement: ``1. Autonomous platforms – The Army ...``
    yields ``Autonomous platforms``.  Hyphens inside a title are untouched.
    """
    title = re.sub(r"\s+", " ", raw or "").strip()
    found = EXPLANATORY_DASH.match(title)
    if found and len(found.group("title").strip()) >= 3:
        title = found.group("title").strip()
    return title


def canonical_marker(marker: str) -> str:
    return "dash" if any(ch in marker for ch in "-–—") else marker.strip()


def raw_candidates(containers):
    """Every line-shaped F1 occurrence, before grouping or acceptance."""
    flat = segmentation._flatten(containers)
    rows = []
    for match in F1_LINE.finditer(flat.text):
        ordinal = int(match.group("ordinal"))
        marker = canonical_marker(match.group("marker"))
        title = clean_title(match.group("title"))
        rows.append(
            segmentation._Candidate(
                code=f"{ordinal}{match.group('marker').strip()}",
                ordinal=ordinal,
                ordinal_label="numeric",
                title=title,
                offset=match.start(),
                page=flat.page_at(match.start()),
                anchor=flat.anchor_at(match.start()),
            )
        )
    return flat, rows


def _marker_for(candidate) -> str:
    code = candidate.code
    suffix = code[len(str(candidate.ordinal)):]
    return canonical_marker(suffix)


def candidate_groups(candidates):
    """Group by document marker and counter run, splitting every restart.

    A run begins only at 1.  It then advances by one or two, exactly mirroring
    §6.4's existing one-gap allowance.  A restart at 1 closes the prior group,
    which preserves 330175's measured 15 + 3 + 6 structure.
    """
    by_marker = defaultdict(list)
    for candidate in candidates:
        by_marker[_marker_for(candidate)].append(candidate)

    groups = []
    for marker, rows in sorted(by_marker.items()):
        current = []
        for candidate in sorted(rows, key=lambda row: row.offset):
            if candidate.ordinal == 1:
                if current:
                    groups.append((marker, tuple(current)))
                current = [candidate]
                continue
            if current and 1 <= candidate.ordinal - current[-1].ordinal <= 2:
                current.append(candidate)
                continue
            if current:
                groups.append((marker, tuple(current)))
            current = []
        if current:
            groups.append((marker, tuple(current)))
    return groups


def _group_signature(group) -> tuple[str, ...]:
    return tuple(normalise_title(row.title) for row in group)


def _group_richness(group, flat) -> tuple[int, int]:
    bounds = segmentation._span_bounds(sorted(group, key=lambda row: row.offset),
                                       len(flat.text))
    lengths = [end - start for start, end in bounds]
    return (sum(lengths), max(lengths, default=0))


def scan_f1(containers):
    """Return raw occurrences, raw groups, accepted groups, and selected groups.

    Acceptance is production's unmodified §6.4 function.  Identical accepted
    title sequences (typically TOC/body copies) are reduced by choosing the one
    with the richer spans; this identity rule was frozen before corpus totals.
    """
    flat, occurrences = raw_candidates(containers)
    toc_pages = segmentation.detect_toc_pages(containers)
    raw_groups = candidate_groups(occurrences)
    evaluated = []
    for index, (marker, group) in enumerate(raw_groups, start=1):
        failures = segmentation.acceptance_failures(
            group, flat, toc_pages, family_type="ordinal"
        )
        evaluated.append({
            "group_id": index,
            "marker": marker,
            "ordinals": [row.ordinal for row in group],
            "titles": [row.title for row in group],
            "pages": [row.page for row in group],
            "failures": list(failures),
            "admitted": not failures,
            "candidates": group,
            "richness": _group_richness(group, flat),
        })

    selected_by_signature = {}
    for row in evaluated:
        if not row["admitted"]:
            continue
        signature = _group_signature(row["candidates"])
        previous = selected_by_signature.get(signature)
        if previous is None or row["richness"] > previous["richness"]:
            selected_by_signature[signature] = row
    selected_ids = {row["group_id"] for row in selected_by_signature.values()}
    for row in evaluated:
        row["selected"] = row["group_id"] in selected_ids
    return flat, occurrences, evaluated


def _docx_containers(content: bytes):
    """Measurement-only Word reading, matching the historical survey method."""
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    paragraphs = []
    for paragraph in root.iter(WORD_NS + "p"):
        text = "".join(node.text or "" for node in paragraph.iter(WORD_NS + "t"))
        if text.strip():
            paragraphs.append(text.strip())
    return [{"page": None, "section": "Word notice", "anchor": None,
             "text": "\n".join(paragraphs)}]


def extract_for_measurement(content: bytes, document: dict):
    name = str(document.get("name") or "").casefold()
    media = str(document.get("content_type") or "").casefold()
    if name.endswith(".docx") or "wordprocessingml" in media:
        return _docx_containers(content)
    containers, _extraction = extract_containers(
        content,
        document.get("content_type"),
        document.get("name"),
        document.get("url"),
    )
    return containers


def load_frame(path=DEFAULT_FRAME):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_inputs():
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))["records"]
    catalog = {
        str(row["opportunity_id"]): row
        for row in load_catalog(CATALOG)["opportunities"]
    }
    return evidence, catalog


def resolve_document(record_id, frame, evidence):
    override = frame.get("source_overrides", {}).get(record_id)
    if override:
        return dict(override)
    return dict(evidence[record_id]["document"])


def resolve_parent(record_id, frame, catalog):
    if record_id in catalog:
        return catalog[record_id]
    return frame["archived_parents"][record_id]


def fetch_verified(document):
    response = download_document(document["url"])
    content = response.get("content") or b""
    if not content:
        raise RuntimeError(
            f"no content (status {response.get('status_code')})"
        )
    digest = hashlib.sha256(content).hexdigest()
    if digest != document["sha256"]:
        raise RuntimeError(
            f"document digest mismatch: expected {document['sha256'][:12]}, "
            f"received {digest[:12]}"
        )
    return content


def truth_titles(frame, record_id):
    block = frame.get("truth", {}).get(record_id, {})
    return {
        normalise_title(row["parsed_title"]): row
        for row in block.get("fundable_subjects", [])
    }


def _public_group(row):
    return {key: value for key, value in row.items()
            if key not in {"candidates", "richness"}}


def measure_document(record_id, frame, evidence, catalog, *, session=None):
    document = resolve_document(record_id, frame, evidence)
    parent = resolve_parent(record_id, frame, catalog)
    expected = truth_titles(frame, record_id)
    content = fetch_verified(document)
    containers = extract_for_measurement(content, document)
    flat, occurrences, groups = scan_f1(containers)

    outcomes = []
    offered_titles = set()
    for group in [row for row in groups if row["selected"]]:
        subtopics = segmentation.build_subtopics(
            group["candidates"], flat, containers,
            parent_deadline=parent.get("close_date"),
        )
        result = segmentation.SegmentationResult(
            subtopics=subtopics,
            method="numbered",
            confidence="low",
            family="fm2_measurement_only",
        )
        built = records.build_records(
            parent, result, document=document, as_of=AS_OF,
            provenance=records.INFERRED,
        )
        for record in built:
            captured = []

            def classifier(candidate, *, api_key=None, session=None):
                verdict = cov4.classify_fundability(
                    candidate, api_key=api_key, session=session
                )
                captured.append(verdict)
                return verdict

            kept, diagnostics = cov4.apply_gate(
                parent, [record], document, classifier=classifier,
                session=session,
            )
            verdict = captured[0]
            candidate = cov4.candidate_from_record(parent, record, document)
            ownership = cov4.determine_ownership(candidate)
            norm = normalise_title(record["title"])
            offered_titles.add(norm)
            expected_fundable = "yes" if norm in expected else "no"
            if kept:
                state, reason = records.publication_eligibility(kept[0])
            else:
                state, reason = "dropped", "cov4_rejected"
            outcomes.append({
                "candidate_id": record["subtopic_id"],
                "group_id": group["group_id"],
                "title": record["title"],
                "expected_fundable": expected_fundable,
                "truth_source": expected.get(norm),
                "cov4_ownership": ownership["ownership"],
                "cov4_ownership_basis": ownership["basis"],
                "cov4_fundability": verdict["fundability"],
                "classifier_owned": verdict.get("classifier_owned"),
                "classifier_reason": verdict.get("reason"),
                "classifier_error": verdict.get("error"),
                "classifier_error_detail": verdict.get("detail"),
                "survived_cov4": bool(kept),
                "publication_state": state,
                "publication_reason": reason,
                "gate_diagnostics": diagnostics,
            })

    missing = [row for norm, row in expected.items() if norm not in offered_titles]
    return {
        "opportunity_id": record_id,
        "parent_title": parent.get("title"),
        "document": {
            "url": document["url"],
            "name": document.get("name"),
            "sha256": document["sha256"],
            "content_type": document.get("content_type"),
        },
        "containers": len(containers),
        "raw_occurrences": len(occurrences),
        "raw_groups": len(groups),
        "structurally_admitted_groups": sum(row["admitted"] for row in groups),
        "selected_groups": sum(row["selected"] for row in groups),
        "groups": [_public_group(row) for row in groups],
        "outcomes": outcomes,
        "missing_verified_subjects": missing,
    }


def aggregate(frame, documents):
    by_id = {row["opportunity_id"]: row for row in documents}
    negative_ids = set(frame["populations"]["category_a_negative_ids"])
    validation_ids = set(frame["populations"]["f1_validation_ids"])
    b0_ids = set(frame["populations"]["b0_administrative_ids"])
    eda_id = frame["populations"]["eda_hazard_id"]

    all_outcomes = [item for row in documents for item in row.get("outcomes", [])]
    subject = [row for row in all_outcomes if row["expected_fundable"] == "yes"]
    non_subject = [row for row in all_outcomes if row["expected_fundable"] == "no"]
    missing_subjects = [item for row in documents
                        for item in row.get("missing_verified_subjects", [])]
    api_errors = [row for row in all_outcomes if row["classifier_error"]]

    def corpus(ids):
        rows = [by_id[rid] for rid in ids]
        outcomes = [item for row in rows for item in row.get("outcomes", [])]
        return {
            "documents": len(rows),
            "document_errors": sum(bool(row.get("error")) for row in rows),
            "raw_numbered_candidate_sets": sum(row.get("raw_groups", 0) for row in rows),
            "raw_candidate_spans": sum(row.get("raw_occurrences", 0) for row in rows),
            "structurally_admitted_sets": sum(
                row.get("structurally_admitted_groups", 0) for row in rows),
            "selected_admitted_sets": sum(row.get("selected_groups", 0) for row in rows),
            "spans_offered_to_cov4": len(outcomes),
            "spans_surviving_cov4": sum(row["survived_cov4"] for row in outcomes),
            "publishable": sum(row["publication_state"] == records.PUBLISHABLE
                               for row in outcomes),
            "review": sum(row["publication_state"] == records.REVIEW
                           for row in outcomes),
            "dropped": sum(row["publication_state"] == "dropped"
                            for row in outcomes),
            "api_errors": sum(bool(row["classifier_error"]) for row in outcomes),
        }

    negative = corpus(negative_ids)
    f1_validation = corpus(validation_ids)
    b0 = corpus(b0_ids)
    eda = corpus({eda_id})
    false_rejections = [row for row in subject if not row["survived_cov4"]]
    false_positives = [row for row in non_subject if row["survived_cov4"]]

    groups_330175 = []
    for group in by_id["330175"].get("groups", []):
        if group["selected"]:
            subject_count = sum(
                normalise_title(title) in truth_titles(frame, "330175")
                for title in group["titles"]
            )
            if subject_count:
                groups_330175.append(subject_count)

    title_355150 = {
        row["title"]: row["survived_cov4"]
        for row in by_id["355150"].get("outcomes", [])
        if row["expected_fundable"] == "yes"
    }

    return {
        "verified_subjects": len(subject) + len(missing_subjects),
        "verified_subjects_offered": len(subject),
        "verified_subjects_accepted": sum(row["survived_cov4"] for row in subject),
        "verified_subjects_cov4_rejected": len(false_rejections),
        "verified_subjects_structurally_missed": len(missing_subjects),
        "false_rejection_candidate_ids": [row["candidate_id"] for row in false_rejections],
        "missing_verified_subjects": missing_subjects,
        "non_subject_candidates_offered": len(non_subject),
        "non_subject_candidates_surviving_cov4": len(false_positives),
        "false_positive_candidate_ids": [row["candidate_id"] for row in false_positives],
        "api_errors": len(api_errors),
        "api_error_candidate_ids": [row["candidate_id"] for row in api_errors],
        "f1_validation": f1_validation,
        "category_a_33": negative,
        "b0_administrative": b0,
        "eda_347414": eda,
        "restart_groups_330175": groups_330175,
        "restart_groups_correct": sorted(groups_330175) == [3, 6, 15],
        "titles_355150": title_355150,
        "title_355150_correct": (
            len(title_355150) == 16
            and "Autonomous platforms" in title_355150
            and all("The Army" not in title for title in title_355150)
        ),
    }


def run(frame_path=DEFAULT_FRAME, out_path=DEFAULT_OUT):
    frame = load_frame(frame_path)
    evidence, catalog = load_inputs()
    record_ids = []
    for population in (
        frame["populations"]["f1_validation_ids"],
        frame["populations"]["category_a_negative_ids"],
        frame["populations"]["b0_administrative_ids"],
        [frame["populations"]["eda_hazard_id"]],
    ):
        for record_id in population:
            if record_id not in record_ids:
                record_ids.append(record_id)

    import requests
    session = requests.Session()
    documents = []
    for record_id in record_ids:
        try:
            documents.append(measure_document(
                record_id, frame, evidence, catalog, session=session
            ))
        except Exception as exc:                 # measurement failure is evidence
            documents.append({
                "opportunity_id": record_id,
                "error": type(exc).__name__,
                "error_detail": str(exc)[:300],
                "raw_occurrences": 0,
                "raw_groups": 0,
                "structurally_admitted_groups": 0,
                "selected_groups": 0,
                "groups": [],
                "outcomes": [],
                "missing_verified_subjects": list(
                    truth_titles(frame, record_id).values()
                ),
            })

    result = {
        "schema_version": 1,
        "frame": str(Path(frame_path).relative_to(ROOT)).replace("\\", "/"),
        "frame_sha256": hashlib.sha256(
            Path(frame_path).read_bytes()
        ).hexdigest(),
        "production_cov4_model": cov4.MODEL,
        "production_cov4_repeats": cov4.REPEATS,
        "documents": documents,
    }
    result["summary"] = aggregate(frame, documents)
    Path(out_path).write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    summary = result["summary"]
    print(f"documents processed: {len(documents)}")
    print(f"verified subjects accepted: {summary['verified_subjects_accepted']}/"
          f"{summary['verified_subjects']}")
    print(f"33-negative false-positive children: "
          f"{summary['category_a_33']['spans_surviving_cov4']}")
    print(f"API errors: {summary['api_errors']}")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame", type=Path, default=DEFAULT_FRAME)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    run(args.frame, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
