"""P5's package gate, recomputed offline from committed artifacts.

Usage:
    python tools/p5_coverage_report.py

**Why this exists.** P5's gate asks for the unreachable-record count *against the
catalog*, and for Cov1/Cov2/Cov3's *reached* and *yielding* figures reported
separately. Both need per-attachment metadata, which the caches do not keep --
only `attachment_count` survives enrichment. `attach_meta.jsonl`, the survey's
own census, was never committed (**DEBT-11**), so P5's closeout re-derived it
from 815 live detail fetches and froze the result as
`evaluation/attachment_census.jsonl`. This script reads that plus the committed
catalog and reproduces every reachability figure **with no network at all**, so
the closeout's numbers are checkable rather than merely reported.

**Reachability is computed with production's own predicates** -- `source_for_record`,
`subtopic_only_primary`, `_skippable`, `_is_html_stub`, `MAX_ATTACHMENTS` -- so a
change to any of them moves these numbers, which is the point.

**Yields are sampled, never censused, and every one carries its denominator.** A
yield census would cost roughly 4,000 document fetches; the gate asks for the two
numbers to be reported separately, not for both to be complete.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import subtopic_sources                                # noqa: E402
from scripts.extract_document_evidence import source_for_record     # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CENSUS = ROOT / "evaluation" / "attachment_census.jsonl"
CATALOG = ROOT / "data" / "opportunities.js"

# Sampled yields, each with the session that produced it. Kept here rather than
# recomputed because the reads were live and are not reproducible offline.
COV1_READS, COV1_HITS = 60, 1        # 10 Cov1 trial + 50 Cov7 stratum-D sample
COV2_READS, COV2_HITS = 22, 0        # 20 Cov2 + 2 Cov7 D-NIH seats
COV3_SECONDARY_WINS = ("349554",)    # AFRL PACER, 18 spans
POST_MEASUREMENT_ID_PREFIXES = ("arpa-h:",)


def wilson(hits, n, z=1.96):
    if n == 0:
        return 0.0, 1.0
    p = hits / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def load_catalog():
    """P5's frozen catalog surface, excluding DEC-19's later additions."""
    raw = CATALOG.read_text(encoding="utf-8")
    payload = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    return [
        record for record in payload["opportunities"]
        if not str(record.get("opportunity_id") or "").startswith(
            POST_MEASUREMENT_ID_PREFIXES
        )
    ]


def load_census():
    census = {}
    for line in CENSUS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            census[row["opportunity_id"]] = row.get("attachments") or []
    return census


def fetchable(attachments):
    """Exactly what `attachment_sources` would offer, without the network."""
    out = []
    for attachment in attachments:
        name = attachment.get("file_name") or ""
        if subtopic_sources._skippable(name):
            continue
        if subtopic_sources._is_html_stub(name, attachment.get("size_bytes")):
            continue
        out.append(attachment)
    return out[:subtopic_sources.MAX_ATTACHMENTS]


def report():
    records = load_catalog()
    census = load_census()
    by_id = {str(r["opportunity_id"]): r for r in records}
    declined = [r for r in records if source_for_record(r) is None]

    reached = unreachable = 0
    for record in declined:
        rid = str(record["opportunity_id"])
        if fetchable(census.get(rid, [])) or subtopic_sources.subtopic_only_primary(
                record):
            reached += 1
        else:
            unreachable += 1

    html_reached = stub_only = 0
    for attachments in census.values():
        html = [a for a in attachments
                if (a.get("file_name") or "").lower().endswith((".html", ".htm"))]
        if not html:
            continue
        if any(not subtopic_sources._is_html_stub(a.get("file_name"),
                                                  a.get("size_bytes"))
               for a in html):
            html_reached += 1
        else:
            stub_only += 1

    multi = [rid for rid, a in census.items() if len(fetchable(a)) > 1]
    multi_primary = [rid for rid in multi
                     if source_for_record(by_id[rid]) is not None]

    figures = {
        "catalog_records": len(records),
        "source_for_record_declines": len(declined),
        "cov1_reached": reached,
        "cov1_unreachable": unreachable,
        "cov1_reads": COV1_READS,
        "cov1_hits": COV1_HITS,
        "cov2_reached": html_reached,
        "cov2_stub_only": stub_only,
        "cov2_reads": COV2_READS,
        "cov2_hits": COV2_HITS,
        "cov3_multi_attachment": len(multi),
        "cov3_reached": len(multi_primary),
        "cov3_secondary_wins": len(COV3_SECONDARY_WINS),
    }

    print("P5 package gate -- clauses 1 and 2, offline")
    print(f"  catalog records                       {figures['catalog_records']:5}")
    print(f"  source_for_record declines            "
          f"{figures['source_for_record_declines']:5}  "
          f"({figures['source_for_record_declines']/len(records):.1%})")
    print()
    print("  Cov1 -- subtopic-only path")
    print(f"    REACHED                             {reached:5}")
    print(f"    UNREACHABLE under every rule        {unreachable:5}  "
          f"({unreachable/len(records):.1%} of the catalog)")
    low, high = wilson(COV1_HITS, COV1_READS)
    print(f"    YIELDING  {COV1_HITS} of {COV1_READS} read = "
          f"{COV1_HITS/COV1_READS:.1%}  Wilson {low:.1%}-{high:.1%}  "
          f"-> {low*reached:.0f}-{high*reached:.0f} of the reached")
    print()
    print("  Cov2 -- HTML attachment support")
    print(f"    REACHED (non-stub .html)            {html_reached:5}")
    print(f"    stub-only, correctly filtered       {stub_only:5}")
    low, high = wilson(COV2_HITS, COV2_READS)
    print(f"    YIELDING  {COV2_HITS} of {COV2_READS} read = "
          f"{COV2_HITS/COV2_READS:.1%}  Wilson {low:.1%}-{high:.1%}  "
          f"-> 0-{high*html_reached:.0f} of the reached")
    print()
    print("  Cov3 -- multi-attachment fetch")
    print(f"    records offering >1 attachment      {len(multi):5}")
    print(f"    REACHED (also carry a primary)      {len(multi_primary):5}")
    print(f"    YIELDING from a SECONDARY           "
          f"{len(COV3_SECONDARY_WINS):5}  ({', '.join(COV3_SECONDARY_WINS)})")
    return figures


if __name__ == "__main__":
    report()
