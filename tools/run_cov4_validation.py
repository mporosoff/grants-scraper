"""Bounded live validation of the Cov4 gate, through production code.

Usage (the credential is loaded in the same invocation, per section 18.1 Cov4):

    $env:ANTHROPIC_API_KEY = [Environment]::GetEnvironmentVariable("ANTHROPIC_API_KEY","User")
    python tools/run_cov4_validation.py

**This is validation, not an experiment.** Nothing here re-tunes anything: the
prompt is `scripts.subtopic_cov4.PROMPT` (the frozen O1 two-axis prompt), the
model is `claude-sonnet-5`, R=1, and the ownership guard is production's. The
candidate population is the **frozen** one -- `evaluation/cov4_ownership.json`
plus `evaluation/cov4_challenge.json`, with the same `source_kind` assignment
rule `tools/run_cov4_ownership.py` committed -- and its truth labels are read,
never rewritten.

**Why it drives `apply_gate` rather than a private loop.** The point of the
exercise is that *production's* gate behaves as measured, so every candidate is
turned into a real section 5.1 record by `subtopic_records.build_records` and
handed to `scripts.subtopic_cov4.apply_gate`. The provenance bypass is included
in the same run, using the real NASA ROSES rows and the real Army TDAC fixture,
so "bypassed by provenance" is a count from the same code path rather than a
separate claim.

Bounded: 43 generic candidates, one call each, plus zero calls for the bypassed
children.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from scripts import subtopic_cov4 as cov4                      # noqa: E402
from scripts import subtopic_records as records                # noqa: E402
from scripts.subtopic_segmentation import (                    # noqa: E402
    SegmentationResult, Subtopic,
)
from tools.run_cov4_ownership import load_candidates           # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
DEFAULT_OUT = ROOT / "evaluation" / "cov4_validation_runs.jsonl"
AS_OF = "2026-08-26"


def _span(candidate, ordinal):
    code = candidate.get("subtopic_code") or candidate["candidate_id"]
    title = candidate.get("title") or code
    summary = candidate.get("excerpt") or ""
    return Subtopic(
        subtopic_code=code,
        subtopic_code_norm=candidate["candidate_id"],
        subtopic_ordinal=ordinal,
        ordinal_label="numeric",
        title=title,
        title_fingerprint=title.casefold(),
        summary=summary,
        subtopic_terms={},
        page_start=candidate.get("page"),
        page_end=candidate.get("page"),
        anchor=None,
        char_start=0,
        char_end=len(summary),
        program_area_labels=(),
        topic_areas=(),
        own_deadline=None,
    )


def generic_records():
    """The 43 frozen candidates as real section 5.1 `inferred` records.

    One record per candidate, each with its own single-span parent, because the
    gate judges spans and the frozen set mixes parents freely.
    """
    prepared = []
    for candidate in load_candidates():
        parent = {
            "opportunity_id": candidate.get("parent_opportunity_id"),
            "opportunity_number": candidate.get("parent_opportunity_number"),
            "title": candidate.get("parent_title"),
            "status": "posted",
        }
        document = {
            "url": candidate.get("source_document_url"),
            "name": candidate.get("source_document_name"),
            "sha256": None,
            "source_kind": candidate.get("source_kind"),
        }
        built = records.build_records(
            parent,
            SegmentationResult(subtopics=(_span(candidate, 1),),
                               method="numbered", confidence="medium",
                               family="topic_area"),
            document=document,
            as_of=AS_OF,
        )
        prepared.append((candidate, parent, document, built))
    return prepared


def bypassed_records():
    """Real `native` and `referenced` children, for the provenance count."""
    from scripts import subtopic_referenced as referenced
    from scripts.sources.adapters.nasa_roses import NasaRosesAdapter
    from scripts.sources.base import SourceAdapter

    adapter = NasaRosesAdapter.__new__(NasaRosesAdapter)
    SourceAdapter.__init__(adapter)
    adapter._client = None
    rows = adapter.rows({
        "table3_html": (FIXTURES / "roses" / "table3.html").read_text(
            encoding="utf-8")
    })
    _overview, elements = adapter.split_rows(rows)
    native = adapter.subtopic_children(
        rows,
        parent_matches={element["identity"]: f"3632{index:02d}"
                        for index, element in enumerate(elements[:5])},
        as_of=AS_OF,
    )

    army_parent = {
        "opportunity_id": "345241",
        "opportunity_number": "W911NF-23-S-0003",
        "title": "DEVCOM ANALYSIS CENTER BROAD AGENCY ANNOUNCEMENT",
        "status": "posted",
    }
    page = (FIXTURES / "army_tdac" / "topics.html").read_text(encoding="utf-8")
    result, document, _diagnostics = referenced.first_refusal(
        army_parent, fetch=lambda _url: page)
    referenced_children = records.build_records(
        army_parent, result, document=document, as_of=AS_OF,
        provenance=records.REFERENCED,
    )
    return native, (army_parent, document, referenced_children)


def run(out_path=DEFAULT_OUT, live=True):
    import requests

    session = requests.Session() if live else None
    rows = []
    totals = collections.Counter()
    ownership_counts = collections.Counter()
    fundability_counts = collections.Counter()
    error_counts = collections.Counter()

    # --- provenance bypass, counted from the same gate --------------------
    native, (army_parent, army_document, army_children) = bypassed_records()
    _kept, native_diag = cov4.apply_gate(
        {"title": "NASA ROSES"}, native, None, session=session)
    _kept, army_diag = cov4.apply_gate(
        army_parent, army_children, army_document, session=session)
    bypassed = collections.Counter()
    for diagnostics in (native_diag, army_diag):
        bypassed.update(diagnostics["bypassed_provenance"])
        totals["bypass_classifier_calls"] += diagnostics["classifier_calls"]

    # --- the 43 generic candidates ---------------------------------------
    genuine_kept = genuine_lost = 0
    contaminants_rejected = contaminants_published = 0
    cross_prevented = cross_published = 0
    unresolved_truth = 0

    for candidate, parent, document, built in generic_records():
        kept, diagnostics = cov4.apply_gate(
            parent, built, document, session=session)
        record = (kept or [None])[0]
        ownership = (record or {}).get("cov4_ownership")
        fundability = (record or {}).get("cov4_fundability")
        if record is None:
            # Dropped: recompute the two axes for the report from diagnostics.
            ownership = next(iter(diagnostics["ownership"]), None)
            fundability = next(iter(diagnostics["fundability"]), None)
        published = diagnostics["published"] == 1
        review = diagnostics["review"] == 1

        ownership_counts[ownership] += 1
        fundability_counts[fundability] += 1
        for error, count in diagnostics["classifier_errors"].items():
            error_counts[error] += count
        totals["offered"] += diagnostics["offered"]
        totals["classifier_calls"] += diagnostics["classifier_calls"]
        totals["published"] += diagnostics["published"]
        totals["dropped"] += diagnostics["dropped"]
        totals["review"] += diagnostics["review"]

        truth_owned = candidate["owned"]
        truth_fundable = candidate["fundable"]
        if "unresolved" in (truth_owned, truth_fundable):
            unresolved_truth += 1
        elif truth_owned == "yes" and truth_fundable == "yes":
            genuine_kept += published
            genuine_lost += not published
        elif truth_owned == "no":
            cross_prevented += not published
            cross_published += published
        else:
            contaminants_rejected += not published
            contaminants_published += published

        rows.append({
            "candidate_id": candidate["candidate_id"],
            "set_name": candidate["set_name"],
            "source_kind": candidate.get("source_kind"),
            "provenance": built[0]["subtopic_source"],
            "truth_owned": truth_owned,
            "truth_fundable": truth_fundable,
            "cov4_ownership": ownership,
            "cov4_fundability": fundability,
            "published": published,
            "review": review,
            "classifier_errors": diagnostics["classifier_errors"],
        })

    out_path = pathlib.Path(out_path)
    with out_path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    report = {
        "model": cov4.MODEL,
        "repeats": cov4.REPEATS,
        "live": live,
        "candidates_offered": totals["offered"],
        "candidates_bypassed_by_provenance": dict(sorted(bypassed.items())),
        "bypass_classifier_calls": totals["bypass_classifier_calls"],
        "classifier_calls": totals["classifier_calls"],
        "ownership_outcomes": dict(sorted(
            (str(k), v) for k, v in ownership_counts.items())),
        "fundability_outcomes": dict(sorted(
            (str(k), v) for k, v in fundability_counts.items())),
        "api_errors": dict(sorted(error_counts.items())),
        "genuine_children_retained": genuine_kept,
        "genuine_children_lost": genuine_lost,
        "contaminants_rejected": contaminants_rejected,
        "contaminants_published": contaminants_published,
        "cross_opportunity_fabrications_prevented": cross_prevented,
        "cross_opportunity_fabrications_published": cross_published,
        "unresolved_truth_cases": unresolved_truth,
        "review_queue_cases": totals["review"],
        "dropped": totals["dropped"],
        "net_auto_publishable_before_cov4": totals["offered"],
        "net_auto_publishable_after_cov4": totals["published"],
        "raw": str(out_path),
    }
    print(json.dumps(report, indent=2))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--offline", action="store_true",
        help="Exercise the harness with no credential; every span goes to "
             "review, which is the fail-closed outcome and not a result.",
    )
    args = parser.parse_args(argv)
    run(args.out, live=not args.offline)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
