"""P7.1's residual-yield tables, recomputed offline from the frozen artifact.

**What this answers.** P7's four recogniser items — `Fm1` named/bulleted,
`Fm2` bare-numbered, `Fm5` tabular, `Fm6` coded-named-list — carry yields
measured on a corpus in which **no structured source had been tried and three
generic repairs had not landed**. §18.1's P7 note makes recomputing that residual
a precondition for building any of them. This script is the recomputation: it
reads `evaluation/p7_residual.json`, which freezes what production's own path
returns for every historically form-bearing record, and derives the residual
counts and their intervals from those rows rather than restating them.

**Four states, and they are not the same thing** (§18.1 P7.1, and instruction 9
of the P7.1 brief):

* `recovered_generic` — production's current generic path produces the children
  today. Whether they publish is Cov6's question, not this one.
* `recovered_referenced` / `recovered_native` — a structured source asserts the
  relationship, so the record is **not** a candidate for a new recogniser.
* `residual_no_family` — the list is there, no family shape covers it. This is
  the population a new recogniser would address.
* `unreachable` — no bytes arrive. Not a measured zero (`FAMILY_TAXONOMY.md` §1),
  and not a recogniser opportunity either.

Yields are reported **as records, with the denominator that produced them**. The
historical per-form catalog extrapolations came from the stratified draws' rates
(survey 40 + taxonomy 50, and Cov7's 30 for stratum D); this script rescales them
by the measured residual share **of the same random observations**, never of the
hand-picked census 20 (`FAMILY_TAXONOMY.md` §4.2).

**One row has moved since, and the artifact is deliberately not rewritten.**
`evaluation/p7_residual.json` is a dated record of what production returned on
2026-08-20 *before* P7.2. **P7.2's BUG-2 repair recovered `363000`** — FEMA's CTP
NOFO prints its three allowable project types as `Category 1-` / `Category 2 -` /
`Category 3.`, which `technical_category` could not match until the ASCII hyphen
and the period entered its delimiter class — so `Fm1`'s residual is **8 records /
45 children**, not the 9 / 48 this script prints from the frozen rows. The survey
had also labelled that record F4 on a *bulleted* rendering of the same three
types; the coded rendering in Appendix C is the one a family can reach. See
§18.1 P7.2.

Usage::

    python tools/p7_residual_report.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.p5_coverage_report import wilson                      # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "evaluation" / "p7_residual.json"

#: The catalog extrapolation each form carried into P7, and where it came from.
#: These are the numbers P7.1 was asked to recompute, quoted so the before/after
#: is legible without opening the plan.
HISTORICAL = {
    "F1": {"item": "Fm2", "records_in_90": 8, "catalog": "~31 (Wilson 47-210 pooled)",
           "source": "FAMILY_TAXONOMY.md §4.4 / TOPIC_LAYER_PLAN.md §18.3a"},
    "F3": {"item": "Fm6", "records_in_90": 4, "catalog": "~6",
           "source": "FAMILY_TAXONOMY.md §4.4"},
    "F4": {"item": "Fm1", "records_in_90": 9, "catalog": "~73, ~22 excluding one stratum-E observation",
           "source": "FAMILY_TAXONOMY.md §4.4 / P5 closeout (10 with Cov7's 359782)"},
    "F5": {"item": "Fm5", "records_in_90": 1, "catalog": "~12 (2-60), re-sized from ~40 by Cov7",
           "source": "evaluation/cov7_stratum_d.json / §18.1 Fm5"},
    "Fm8": {"item": "Fm8", "records_in_90": 0, "catalog": "n=1, no estimate supportable",
            "source": "evaluation/cov7_stratum_d.json"},
}

RECOVERED = ("recovered_generic", "recovered_referenced", "recovered_native")
RESIDUAL = ("residual_no_family", "residual_rule_rejected")


def load():
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def by_form(artifact):
    """Grouped by form, with the three fixture records held apart.

    A fixture record is not a form observation: it is a record measured because a
    recogniser would wrongly fire on it, so counting it in a residual would invert
    its meaning.
    """
    grouped = {}
    for row in artifact["frame_r_records"]:
        if row["form"] == "FIXTURE":
            continue
        grouped.setdefault(row["form"], []).append(row)
    return grouped


def fixtures(artifact):
    return [row for row in artifact["frame_r_records"] if row["form"] == "FIXTURE"]


def residual_table(artifact):
    """Per-form residual, derived from the per-record states rather than stored."""
    table = {}
    for form, rows in sorted(by_form(artifact).items()):
        observations = len(rows)
        # Two random denominators, kept apart on purpose. The historical catalog
        # point estimates were computed on the survey+taxonomy draws only (the 87
        # measurable stratified reads); Cov7's 30 stratum-D reads are a separate
        # draw and were folded into stratum D's own estimate, never into a form's.
        stratified_rows = [r for r in rows if r["sample"] in ("survey", "taxonomy")]
        random_rows = [r for r in rows if r["sample"] != "census"]
        recovered = [r for r in rows if r["state"] in RECOVERED]
        residual = [r for r in rows if r["state"] in RESIDUAL]
        unreachable = [r for r in rows if r["state"] == "unreachable"]
        residual_random = [r for r in random_rows if r["state"] in RESIDUAL]
        residual_stratified = [r for r in stratified_rows if r["state"] in RESIDUAL]
        low, high = wilson(len(residual_stratified), 87)
        children = sum(r["historical_children"] or 0 for r in residual)
        table[form] = {
            "item": HISTORICAL[form]["item"],
            "historical_observations": observations,
            "historical_random_observations": len(random_rows),
            "recovered": [r["opportunity_id"] for r in recovered],
            "recovered_by": sorted({r["state"] for r in recovered}),
            "residual": [r["opportunity_id"] for r in residual],
            "unreachable": [r["opportunity_id"] for r in unreachable],
            "residual_records": len(residual),
            "residual_random_records": len(residual_random),
            "residual_children": children,
            "agencies": sorted({r["agency"] for r in residual}),
            "residual_share_of_random": (
                len(residual_random) / len(random_rows) if random_rows else None
            ),
            "historical_stratified_observations": len(stratified_rows),
            "residual_stratified_records": len(residual_stratified),
            "residual_rate_on_87_stratified_reads": (
                len(residual_stratified) / 87 if stratified_rows else None
            ),
            "wilson_95_on_87": [low, high] if stratified_rows else None,
            "catalog_band_from_87": (
                [round(low * 1475), round(high * 1475)] if stratified_rows else None
            ),
        }
    return table


def frame_s_summary(artifact):
    rows = artifact["frame_s_records"]
    read = [r for r in rows if r["documents_read"]]
    hits = [r for r in rows if r["fm8_hits"]]
    low, high = wilson(len(hits), len(rows))
    return {
        "records": len(rows),
        "records_with_a_readable_document": len(read),
        "documents_read": sum(r["documents_read"] for r in rows),
        "documents_unreadable_content_type": sum(
            r["documents_unreadable"] for r in rows),
        "records_with_no_readable_document": len(rows) - len(read),
        "fm8_hits": len(hits),
        "wilson": [low, high],
        "records_with_any_span": sum(1 for r in rows if r["spans"]),
    }


def main():
    artifact = load()
    print("P7.1 residual measurement, recomputed offline from "
          "evaluation/p7_residual.json")
    print(f"  measured           {artifact['measured_at']}")
    print(f"  code commit        {artifact['code_commit']}")
    print(f"  catalog            {artifact['frames']['catalog_records']} records, "
          f"generated {artifact['frames']['catalog_generated_at']}")
    print()

    print("  Frame R -- historical form-bearing census, state today")
    table = residual_table(artifact)
    for form, row in table.items():
        hist = HISTORICAL[form]
        print(f"    {form:4} -> {row['item']:4}  historical {row['historical_observations']:2}"
              f" observations ({row['historical_random_observations']} random)"
              f"  historical catalog estimate {hist['catalog']}")
        print(f"          recovered {len(row['recovered']):2} "
              f"{row['recovered_by'] or ''} {row['recovered']}")
        print(f"          residual  {row['residual_records']:2} "
              f"({row['residual_random_records']} random)  {row['residual']}")
        print(f"          unreachable {len(row['unreachable']):2} {row['unreachable']}")
        print(f"          residual children {row['residual_children']:3}"
              f"  agencies {row['agencies']}")
        share = row["residual_share_of_random"]
        if share is not None:
            print(f"          residual share of all random observations "
                  f"{len(row['residual']) if False else row['residual_random_records']}"
                  f"/{row['historical_random_observations']} = {share:.0%}")
        if row["wilson_95_on_87"]:
            low, high = row["wilson_95_on_87"]
            print(f"          on the 87 measurable stratified reads: "
                  f"{row['residual_stratified_records']}/87 = "
                  f"{row['residual_rate_on_87_stratified_reads']:.2%}  Wilson "
                  f"{low:.1%}-{high:.1%} -> {row['catalog_band_from_87'][0]}-"
                  f"{row['catalog_band_from_87'][1]} records")
        print()

    print("  Frame R -- the three required false-positive fixtures")
    for row in fixtures(artifact):
        print(f"    {row['opportunity_id']}  {row['agency'][:34]:34} "
              f"families {row['families_firing']}  best_family "
              f"{row['best_family_body']}  refused by "
              f"{row['acceptance_failures_body'] or 'nothing -- no family fires'}")
    print()

    print("  Frame S -- Fm8 document-surface sample")
    summary = frame_s_summary(artifact)
    for key, value in summary.items():
        print(f"    {key:38} {value}")
    print()

    print("  Frame C -- offline catalog text census")
    for key, value in artifact["frames"]["frame_c"].items():
        print(f"    {key:38} {value}")
    print()

    print("  no_extractable_text, reported per cause and per denominator")
    for name, block in artifact["extraction_causes"].items():
        if not isinstance(block, dict):
            print(f"    {name}: {block}")
            continue
        print(f"    {name}")
        for key, value in block.items():
            print(f"      {key:36} {value}")
    print()

    print("  P7 recommendation after P7.1")
    for row in artifact["recommendations"]:
        print(f"    {row['item']:5} {row['form']:22} {row['recommendation']:28}"
              f" residual {row['residual_records']} records / "
              f"{row['residual_children']} children")
        print(f"          {row['because']}")
    return artifact


if __name__ == "__main__":
    main()
