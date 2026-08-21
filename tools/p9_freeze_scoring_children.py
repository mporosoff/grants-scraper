#!/usr/bin/env python3
"""Build the compact, source-grounded P9.1 scoring fixture without network."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re

from scripts.build_subtopics import AS_OF, atomic_json
from scripts.extract_document_evidence import DEFAULT_CATALOG, read_catalog
from scripts.sources.adapters.nasa_roses import NasaRosesAdapter
from scripts.subtopic_referenced import ARMY_TDAC_TOPICS_URL, parse_army_tdac
from scripts.subtopic_segmentation import build_term_map, normalize_code, summarize
from scripts.subtopic_structured import (
    ARL_NUMBER,
    GENESIS_NUMBER,
    HGEO_EXPECTED,
    parse_arl_topics,
    parse_hgeo,
)


DEFAULT_OUTPUT = Path("evaluation/p9_scoring_children.json")
MEAS3 = Path("evaluation/meas3_population.json")
TDAC = Path("tests/fixtures/army_tdac/topics.html")
ROSES = Path("tests/fixtures/roses")
SOURCE_HASHES = {
    "office_science": "60cffb3796f5ff5cbc7eabf76db8d425fac6ef18eae3c9014011ad3d0cafc3ea",
    "genesis": "a2e36829b1c6f1ece1db19e6baf854fb1eff34a41d79efbb6bc60a646a9e3517",
    "arl": "c9ab5dd5a95c0f40f68fa4af8b4600c4534e26a15f09a16662e53fb795ba8b24",
    "hgeo_363065": "bd02be187cea901e7a1aac00147f6895eeaf4d76b5057419c300798081779d67",
    "hgeo_363302": "1729f8688feeb6c7dbfc1b97c457386cea4d21091407f5029b764e6aed9350e6",
    "hgeo_363594": "e0d726d61ce719fcdff9da073c9a54542fdb5d5029befbc90d3be57c050090fd",
}


def source_file(directory, prefix):
    found = sorted(Path(directory).glob(f"{prefix}*"))
    if len(found) != 1:
        raise RuntimeError(f"expected one {prefix} source text, found {len(found)}")
    return found[0]


def compact_child(
    parent_id,
    child_id,
    title,
    text,
    *,
    provenance,
    source_group,
    source_hash,
    group_id=None,
    parent_subtopic_id=None,
):
    record = {
        "parent_id": str(parent_id),
        "subtopic_id": str(child_id),
        "child_type": "subject",
        "title": str(title),
        "summary": summarize(str(text)),
        "subtopic_terms": build_term_map(f"{title} {text}"),
        "subtopic_source": provenance,
        "source_group": source_group,
        "source_document_hash": source_hash,
    }
    if group_id:
        record["group_id"] = group_id
    if parent_subtopic_id:
        record["parent_subtopic_id"] = parent_subtopic_id
    return record


def office_science_children():
    population = json.loads(MEAS3.read_text(encoding="utf-8"))
    children = []
    for candidate in population["candidates"]:
        if candidate["parent_opportunity_id"] != "360678":
            continue
        children.append(compact_child(
            "360678",
            candidate["candidate_id"],
            candidate["title"],
            candidate["excerpt"],
            provenance="inferred",
            source_group="office_science_69_upper_bound",
            source_hash=SOURCE_HASHES["office_science"],
        ))
    if len(children) != 69:
        raise RuntimeError(f"Office of Science fixture changed: {len(children)}")
    return children


def genesis_children(text):
    pattern = re.compile(
        r"^(?P<group>\d{1,2})-(?P<letter>[A-Z])\s+"
        r"(?P<challenge>.+?)\s*\|\s*(?P<focus>.+)$"
    )
    rows = [match.groupdict() for line in text.splitlines()
            if (match := pattern.match(line.strip()))]
    groups = {}
    for row in rows:
        groups[row["group"]] = row["challenge"]
    if (len(groups), len(rows)) != (21, 98):
        raise RuntimeError(f"Genesis fixture changed: {len(groups)}/{len(rows)}")
    children = []
    for number in sorted(groups, key=int):
        group_id = f"challenge-{int(number)}"
        children.append(compact_child(
            "361526",
            f"361526:{group_id}",
            groups[number],
            groups[number],
            provenance="native",
            source_group="genesis_21_plus_98",
            source_hash=SOURCE_HASHES["genesis"],
            group_id=group_id,
        ))
    for row in rows:
        group_id = f"challenge-{int(row['group'])}"
        code = normalize_code(f"{int(row['group'])}-{row['letter']}")
        children.append(compact_child(
            "361526",
            f"361526:{code}",
            row["focus"],
            f"{row['challenge']} {row['focus']}",
            provenance="native",
            source_group="genesis_21_plus_98",
            source_hash=SOURCE_HASHES["genesis"],
            group_id=group_id,
            parent_subtopic_id=f"361526:{group_id}",
        ))
    return children


def tdac_children():
    html = TDAC.read_text(encoding="utf-8")
    topics = parse_army_tdac(html)
    if len(topics) != 14:
        raise RuntimeError(f"TDAC fixture changed: {len(topics)}")
    import hashlib
    digest = hashlib.sha256(html.encode("utf-8")).hexdigest()
    return [compact_child(
        "345241",
        f"345241:{topic['announcement_id_norm']}",
        topic["title"],
        topic["detail_text"],
        provenance="referenced",
        source_group="tdac_14",
        source_hash=digest,
    ) for topic in topics]


def roses_children(catalog):
    adapter = NasaRosesAdapter()
    payload = {
        "year": 2025,
        "amendment": 69,
        "table3_html": (ROSES / "table3.html").read_text(encoding="utf-8"),
        "table2_html": (ROSES / "table2.html").read_text(encoding="utf-8"),
    }
    rows = adapter.rows(payload)
    health = adapter.check_health(payload, rows)
    if not health["healthy"]:
        raise RuntimeError("ROSES fixture health failed")
    report = adapter.reconcile(
        rows,
        catalog_records=catalog["opportunities"],
        year=2025,
    )
    if len(report["matched"]) != 10:
        raise RuntimeError(f"ROSES match fixture changed: {len(report['matched'])}")
    import hashlib
    digest = hashlib.sha256(payload["table3_html"].encode("utf-8")).hexdigest()
    children = []
    for element in report["matched"]:
        for parent in element["matched_catalog_ids"]:
            code = normalize_code(element["appendix_code"] + "-" + element["title"])
            children.append(compact_child(
                parent,
                f"{parent}:{code}",
                element["title"],
                f"{element['title']} {element['native_deadline_text']}",
                provenance="native",
                source_group="roses_10",
                source_hash=digest,
            ))
    return children


def hgeo_children(truth_dir):
    specs = [
        ("363065", "DE-FOA-0003627", "363065_01_", "hgeo_363065"),
        ("363302", "DE-FOA-0003634", "363302_02_", "hgeo_363302"),
        ("363594", "DE-FOA-0003215", "363594_02_", "hgeo_363594"),
    ]
    children = []
    for parent, number, prefix, hash_key in specs:
        text = source_file(truth_dir, prefix).read_text(encoding="utf-8")
        parsed = parse_hgeo(text, number)
        if len(parsed) != len(HGEO_EXPECTED[number]):
            raise RuntimeError(f"HGEO fixture changed: {parent}/{len(parsed)}")
        for item in parsed:
            children.append(compact_child(
                parent,
                f"{parent}:{normalize_code(item['code'])}",
                item["title"],
                item["summary"],
                provenance="inline",
                source_group="hgeo_4_5_3",
                source_hash=SOURCE_HASHES[hash_key],
            ))
    return children


def arl_children(truth_dir):
    text = source_file(truth_dir, "344592_01_").read_text(encoding="utf-8")
    parsed = parse_arl_topics(text)
    if len(parsed) != 82:
        raise RuntimeError(f"ARL fixture changed: {len(parsed)}")
    return [compact_child(
        "344592",
        f"344592:{normalize_code(item['code'])}",
        item["title"],
        item["summary"],
        provenance="native",
        source_group="arl_82",
        source_hash=SOURCE_HASHES["arl"],
    ) for item in parsed]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--truth-dir", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    catalog = read_catalog(args.catalog)
    genesis_text = source_file(args.truth_dir, "361526_03_").read_text(encoding="utf-8")
    children = (
        office_science_children()
        + genesis_children(genesis_text)
        + tdac_children()
        + roses_children(catalog)
        + hgeo_children(args.truth_dir)
        + arl_children(args.truth_dir)
    )
    identities = [child["subtopic_id"] for child in children]
    if len(identities) != len(set(identities)):
        raise RuntimeError("scoring fixture contains duplicate child identities")
    counts = Counter(child["source_group"] for child in children)
    payload = {
        "schema_version": 1,
        "as_of": AS_OF,
        "purpose": "P9.1 cross-corpus normalization and cardinality stress fixture",
        "admission_note": (
            "Includes the 69-child Office of Science generic set as an upper-bound "
            "stress case; production publication still obeys Cov6/DEC-16."
        ),
        "record_count": len(children),
        "source_group_counts": dict(sorted(counts.items())),
        "records": sorted(children, key=lambda item: (
            item["parent_id"], item["subtopic_id"]
        )),
    }
    atomic_json(payload, args.output)
    print(json.dumps({
        "records": payload["record_count"],
        "groups": payload["source_group_counts"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
