"""Freeze the Cov4 ownership cases, with human labels committed before any run.

Usage: python tools/build_cov4_ownership_set.py [--out evaluation/cov4_ownership.json]

Separate artifact. Neither `meas3_population.json` nor `cov4_challenge.json` is
modified — both remain exactly as measured.

Every row is **real document text** from a document this project has fetched and
digest-verified, and carries the `source_kind` the production pipeline would attach,
because that is the evidence O2 actually decides on.

Two labels per row, because ownership and fundability are two axes:

* ``owned``    — ``yes`` this belongs to the parent | ``no`` it belongs elsewhere
* ``fundable`` — ``yes`` genuine child | ``no`` contaminant | ``unresolved``
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_OUT = Path("evaluation/cov4_ownership.json")

#: The seven ownership scenarios the brief requires, each drawn from a real document.
CASES = [
    # 1. explicit same-parent opportunity number, on the parent's own attachment
    {
        "candidate_id": "own:360678-same-number",
        "scenario": "explicit_same_parent_number",
        "parent_opportunity_id": "360678",
        "parent_opportunity_number": "DE-FOA-0003600",
        "parent_title": "FY 2026 Continuation of Solicitation for the Office of Science Financial Assistance Program",
        "source_kind": "primary_notice",
        "source_document_name": "DE-FOA-0003600.000001.pdf",
        "source_document_url": "https://apply07.grants.gov/grantsws/rest/opportunity/att/download/349515",
        "subtopic_code": "(q) Catalysis Science",
        "title": "(q) Catalysis Science",
        "excerpt": "This program supports fundamental research in catalysis science "
                   "under Funding Opportunity Announcement DE-FOA-0003600, addressing "
                   "the discovery and design of catalytic systems.",
        "owned": "yes",
        "fundable": "yes",
        "label_evidence": "The parent's own primary attachment, and the text names the "
                          "parent number itself. Catalysis Science is the programme "
                          "§6.7 was written around (census: level 2, page 46)",
    },
    # 2. explicit different-parent number, on an agency aggregator page
    {
        "candidate_id": "own:363594-foreign-number",
        "scenario": "explicit_different_parent_number",
        "parent_opportunity_id": "363594",
        "parent_opportunity_number": "DE-FOA-0003215",
        "parent_title": "Annual Recurring University Training and Research",
        "source_kind": "subtopic_agency_notice",
        "source_document_name": None,
        "source_document_url": "https://netl-exchange.energy.gov/Default.aspx",
        "subtopic_code": "Topic Area 1",
        "title": "Topic Area 1: Improved Oil and Gas Recovery",
        "excerpt": "Topic Area 1: Improved Oil and Gas Recovery — an area of interest "
                   "under DE-FOA-0003627, listed among many open NETL funding "
                   "opportunities on this page.",
        "owned": "no",
        "fundable": "yes",
        "label_evidence": "BUG-9 / FAMILY_TAXONOMY §4.6: NETL's aggregating landing "
                          "page, where topic_area fires 10 times and every topic "
                          "belongs to a different opportunity. Semantically a real "
                          "topic — which is why ownership must be a separate axis",
    },
    # 3. no opportunity number anywhere in the excerpt, parent's own attachment
    {
        "candidate_id": "own:361526-no-number",
        "scenario": "no_opportunity_number_in_excerpt",
        "parent_opportunity_id": "361526",
        "parent_opportunity_number": "DE-FOA-0003612",
        "parent_title": "The Genesis Mission: Transforming Science and Energy with AI",
        "source_kind": "primary_notice",
        "source_document_name": "DE-FOA-0003612.000003.pdf",
        "source_document_url": "https://apply07.grants.gov/grantsws/rest/opportunity/att/download/354251",
        "subtopic_code": "2 - Scaling the Biotechnology Revolution",
        "title": "2 - Scaling the Biotechnology Revolution",
        "excerpt": "Challenge: Biotechnology is poised to transform manufacturing, "
                   "medicine and agriculture. This challenge area seeks AI-enabled "
                   "approaches to accelerate biological design and scale-up.",
        "owned": "yes",
        "fundable": "yes",
        "label_evidence": "One of the 21 Genesis Mission challenge areas the census "
                          "verified as exactly the published list; the excerpt names "
                          "no solicitation number at all, which is the common case",
    },
    # 4. multiple numbers in amendment prose, parent's own attachment
    {
        "candidate_id": "own:363065-amendment-history",
        "scenario": "multiple_numbers_in_amendment_prose",
        "parent_opportunity_id": "363065",
        "parent_opportunity_number": "DE-FOA-0003627",
        "parent_title": "Improved Oil and Gas Recovery and Produced Water Management Technologies",
        "source_kind": "primary_notice",
        "source_document_name": "FundOpp_DE-FOA-0003627_Amd_000003.pdf",
        "source_document_url": "https://apply07.grants.gov/grantsws/rest/opportunity/att/download/355012",
        "subtopic_code": "Topic Area 2",
        "title": "Topic Area 2: Advanced Field-Testing of Multi-Scale Produced Water "
                 "Treatment Technologies & Processes",
        "excerpt": "Topic Area 2: Advanced Field-Testing of Multi-Scale Produced Water "
                   "Treatment Technologies & Processes. Amendment 000003 to "
                   "DE-FOA-0003627 revised Topic Area 1b cost share to 20% and "
                   "revised Section IV.C.2. Version 4.0.",
        "owned": "yes",
        "fundable": "yes",
        "label_evidence": "Quoted from the parent's own amended notice; the amendment "
                          "log repeats the parent number and revises sibling topics. A "
                          "guard that reads prose for numbers must not trip here",
    },
    # 5. agency landing/aggregator page, no number printed at all
    {
        "candidate_id": "own:363594-aggregator-unnumbered",
        "scenario": "agency_landing_page_no_number",
        "parent_opportunity_id": "363594",
        "parent_opportunity_number": "DE-FOA-0003215",
        "parent_title": "Annual Recurring University Training and Research",
        "source_kind": "subtopic_agency_notice",
        "source_document_name": None,
        "source_document_url": "https://netl-exchange.energy.gov/Default.aspx",
        "subtopic_code": "Area of Interest 3",
        "title": "Area of Interest 3: Carbon Storage Field Projects",
        "excerpt": "Area of Interest 3: Carbon Storage Field Projects. Applications "
                   "are sought for integrated field demonstrations of geologic carbon "
                   "storage.",
        "owned": "unresolved",
        "fundable": "yes",
        "label_evidence": "Same aggregating page, but this item prints no solicitation "
                          "number, so the page gives no evidence either way. Labelled "
                          "**unresolved on ownership**: a guard must not guess, and "
                          "must not publish. Excluded from ownership scoring",
    },
    # 6. attachment unambiguously the parent's
    {
        "candidate_id": "own:362233-parent-attachment",
        "scenario": "attachment_unambiguously_parent",
        "parent_opportunity_id": "362233",
        "parent_opportunity_number": "HT942526LRPIA",
        "parent_title": "FY26 Lupus Research Program Idea Award",
        "source_kind": "primary_notice",
        "source_document_name": "HT942526LRPIA_GG.pdf",
        "source_document_url": "https://apply07.grants.gov/grantsws/rest/opportunity/att/download/352233",
        "subtopic_code": "Focus Area",
        "title": "Understanding the biological mechanisms of lupus disease",
        "excerpt": "Understanding the biological mechanisms of lupus disease "
                   "including, but not limited to, studies of informative/rare "
                   "patients.",
        "owned": "yes",
        "fundable": "yes",
        "label_evidence": "The document's filename carries the parent number and "
                          "Grants.gov serves it as this record's attachment; the item "
                          "is one of the 'must address at least one' Focus Areas",
    },
    # 7. legitimate child that descriptively mentions a *different* solicitation
    {
        "candidate_id": "own:360678-predecessor-citation",
        "scenario": "legitimate_child_mentions_other_foa",
        "parent_opportunity_id": "360678",
        "parent_opportunity_number": "DE-FOA-0003600",
        "parent_title": "FY 2026 Continuation of Solicitation for the Office of Science Financial Assistance Program",
        "source_kind": "primary_notice",
        "source_document_name": "DE-FOA-0003600.000001.pdf",
        "source_document_url": "https://apply07.grants.gov/grantsws/rest/opportunity/att/download/349515",
        "subtopic_code": "(h) Quantum Information Science for High Energy Physics Research",
        "title": "(h) Quantum Information Science for High Energy Physics Research",
        "excerpt": "QuantISED in HEP Comparative Review. QuantISED will join the HEP "
                   "comparative review process in FY 2027 for the first time. "
                   "Previously the QuantISED program has been funded through a "
                   "separate NOFO most recently published in FY 2024 (DE-FOA-0003354, "
                   "QuantISED 2.0) and continued with a targeted review in FY 2026.",
        "owned": "yes",
        "fundable": "yes",
        "label_evidence": "**The over-aggression trap.** Quoted verbatim from the "
                          "parent's own primary notice at page 96; it is a genuine HEP "
                          "programme whose text cites a *predecessor* NOFO. Any rule "
                          "of the form 'a foreign number anywhere means reject' "
                          "destroys this child",
    },
]


def build(out_path=DEFAULT_OUT):
    rows = sorted(CASES, key=lambda row: row["candidate_id"])
    counts = {}
    for row in rows:
        counts[row["owned"]] = counts.get(row["owned"], 0) + 1
    payload = {
        "schema_version": 1,
        "purpose": "Cov4 ownership cases — real documents, human-labelled on two axes "
                   "before any strategy was run",
        "invariant": (
            "A candidate may be semantically fundable and still invalid for this "
            "parent if the evidence establishes it belongs to another opportunity. "
            "Ownership and fundability are separate axes and a candidate must pass "
            "both."
        ),
        "immutability": (
            "meas3_population.json and cov4_challenge.json are unchanged. This is a "
            "third, separate artifact."
        ),
        "ownership_label_counts": counts,
        "candidate_count": len(rows),
        "candidates": rows,
    }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    payload = build(args.out)
    print(f"wrote {args.out}: {payload['candidate_count']} ownership cases "
          f"{payload['ownership_label_counts']}")
    for row in payload["candidates"]:
        print(f"  {row['candidate_id']:34} owned={row['owned']:10} "
              f"fundable={row['fundable']:6} kind={row['source_kind']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
