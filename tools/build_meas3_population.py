"""Freeze the MEAS-3 candidate population from committed evidence + production code.

Usage: python tools/build_meas3_population.py [--out evaluation/meas3_population.json]

**Why this exists.** §11's 114-span population came from a backfill that was never
committed, so it cannot be re-run (DEBT-9). This script builds a *new* population
that can, and freezes it so every future MEAS-3 or Cov4 run shares one denominator.

**What makes it deterministic**, which is the whole point:

* the **document identity comes from the committed evidence cache** —
  `data/document_evidence.json` pins a URL *and* a `sha256` per record, and this
  script **verifies the digest and refuses to continue on a mismatch**, so a
  silently-revised PDF is a hard failure rather than a quiet population change;
* the parent record comes from the committed catalog;
* segmentation is the **production path**, unmodified: `extract_containers` then
  `subtopic_segmentation.segment_document`;
* output is sorted and serialized with fixed separators, so byte-identical inputs
  give a byte-identical artifact.

**The artifact carries the semantic input the classifier receives** — title and
excerpt text — not just ids pointing at mutable documents. That is what lets MEAS-3
and Cov4 be re-run offline, and it is a required property (DEBT-9's closure test).

Network is used once per document, to fetch bytes whose digest is already pinned.
Classifying the frozen artifact afterwards needs no network at all.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.extract_document_evidence import (          # noqa: E402
    download_document,
    extract_containers,
)
from scripts.subtopic_records import INFERRED            # noqa: E402
from scripts.subtopic_segmentation import (              # noqa: E402
    extractor_version,
    segment_document,
)
from scripts.sources.merge import load_catalog           # noqa: E402

DEFAULT_OUT = Path("evaluation/meas3_population.json")
EVIDENCE = Path("data/document_evidence.json")
CATALOG = Path("data/opportunities.js")

#: **Arm A — the population Cov4 will actually face.** Records whose *primary
#: notice* currently produces accepted spans through production segmentation. This
#: is deliberately not a reconstruction of §11's 114 spans, which is impossible:
#: that artifact was never committed and Cov5 has since changed extraction.
#:
#: `349554` (AFRL PACER) is **excluded and the exclusion is deliberate**: its topics
#: live in a secondary attachment, so reaching them needs the Grants.gov detail API
#: rather than the pinned primary, and that is not deterministic from committed
#: evidence alone.
ARM_A = ("360678", "361526", "356623", "363302", "363526", "362681")

#: **Arm B — the stress shapes §11's population did not contain** (§18.1 Cov4, 8.5).
#: Evaluation only. Nothing here licenses building an F1 or F4 recogniser.
ARM_B = {
    "363594": "aggregating_agency_page",   # BUG-9: another opportunity's topic list
    "330175": "f1_bare_numbered",          # grouped counters restarting at 1.
    "362233": "f4_named_bulleted",         # five real Focus Areas above five decoys
}


def _load_inputs():
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))["records"]
    catalog = {
        str(record["opportunity_id"]): record
        for record in load_catalog(CATALOG)["opportunities"]
    }
    return evidence, catalog


def _fetch_verified(document):
    """Download the pinned document and refuse anything but the recorded digest."""
    response = download_document(document["url"])
    content = response.get("content")
    if not content:
        raise RuntimeError(
            f"no content for {document['url']} (status {response.get('status_code')})"
        )
    digest = hashlib.sha256(content).hexdigest()
    if digest != document["sha256"]:
        raise RuntimeError(
            f"digest mismatch for {document['name']}: committed evidence records "
            f"{document['sha256'][:12]}, fetched {digest[:12]}. The population is "
            "not reproducible from this document; re-freeze deliberately."
        )
    return content


def candidates_for(record_id, arm, evidence, catalog, *, shape=None):
    """Every accepted span of one record, as frozen classifier input."""
    entry = evidence[record_id]
    document = entry["document"]
    record = catalog[record_id]
    content = _fetch_verified(document)
    containers, _extraction = extract_containers(
        content, document.get("content_type"), document.get("name"), document.get("url")
    )
    result = segment_document(
        record, content, containers, document,
        parent_deadline=record.get("close_date"),
    )
    rows = []
    for subtopic in result.subtopics:
        rows.append({
            "candidate_id": f"{record_id}:{subtopic.subtopic_code_norm}",
            "arm": arm,
            "shape": shape,
            "parent_opportunity_id": record_id,
            "parent_opportunity_number": record.get("opportunity_number"),
            "parent_title": record.get("title"),
            "source_document_url": document["url"],
            "source_document_name": document["name"],
            "source_document_sha256": document["sha256"],
            "subtopic_code": subtopic.subtopic_code,
            "ordinal_label": subtopic.ordinal_label,
            "title": subtopic.title,
            # The semantic input Cov4 receives. Frozen here so classification is
            # offline and repeatable.
            "excerpt": subtopic.summary,
            "page_start": subtopic.page_start,
            "page_end": subtopic.page_end,
            "anchor": subtopic.anchor,
            "segmentation_method": result.method,
            "pattern_family": result.family,
            # Everything the generic pipeline produces is `inferred` (§5.1); the
            # rung is recorded so the Cov4 boundary can be asserted against it.
            "provenance": INFERRED,
            "confidence_before_cov4": result.confidence,
            # Filled from measured human judgement where one exists; null means
            # "no measured label", never "negative".
            "truth_label": None,
            "truth_source": None,
        })
    return rows, {
        "record_id": record_id,
        "arm": arm,
        "shape": shape,
        "document_name": document["name"],
        "document_sha256": document["sha256"],
        "pages": (entry.get("extraction") or {}).get("page_count"),
        "segmentation_method": result.method,
        "pattern_family": result.family,
        "confidence": result.confidence,
        "reason": result.reason,
        "accepted_spans": len(result.subtopics),
    }


def build(out_path=DEFAULT_OUT):
    evidence, catalog = _load_inputs()
    candidates, provenance_rows = [], []
    for record_id in ARM_A:
        rows, summary = candidates_for(record_id, "A", evidence, catalog)
        candidates.extend(rows)
        provenance_rows.append(summary)
    for record_id, shape in ARM_B.items():
        rows, summary = candidates_for(record_id, "B", evidence, catalog, shape=shape)
        candidates.extend(rows)
        provenance_rows.append(summary)

    candidates.sort(key=lambda row: (row["arm"], row["parent_opportunity_id"],
                                     row["candidate_id"]))
    payload = {
        "schema_version": 1,
        "purpose": "MEAS-3 / Cov4 frozen candidate population (post-Cov5)",
        "not_comparable_to": (
            "§11's 114-span run: that population came from the uncommitted D4/D5 "
            "backfill and Cov5 has since changed extraction. Historical evidence "
            "motivates repeated classification; it is not a shared denominator."
        ),
        "extractor_version": extractor_version(),
        "arm_a_records": list(ARM_A),
        "arm_b_records": dict(ARM_B),
        "documents": sorted(provenance_rows,
                            key=lambda row: (row["arm"], row["record_id"])),
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(
        (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n")
        .encode("utf-8")
    )
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    payload = build(args.out)
    print(f"wrote {args.out}: {payload['candidate_count']} candidates")
    for row in payload["documents"]:
        print(f"  arm {row['arm']}  {row['record_id']}  spans={row['accepted_spans']:3}  "
              f"method={str(row['segmentation_method']):18} "
              f"conf={str(row['confidence']):7} reason={row['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
