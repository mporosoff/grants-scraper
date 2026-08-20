"""P5 closeout -- the package gate's figures, pinned so they stay checkable.

Offline. What these tests protect is that the gate's numbers can be **re-derived
from committed artifacts**, which is the thing DEBT-11 cost the project once
already: the survey's attachment census was never committed, so P5's closeout had
to rebuild it from 815 live fetches before it could answer clause 1 at all.

They also pin clause 3's publishable set, which is the one figure a future change
could quietly move -- a rung reaching `high` by accident would put records in
front of a PI with no human in the loop.
"""

import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from scripts import subtopic_records as records            # noqa: E402
from scripts import subtopic_referenced as referenced      # noqa: E402
from tools.p5_coverage_report import report, load_census   # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
CENSUS = ROOT / "evaluation" / "attachment_census.jsonl"


class AttachmentCensusTests(unittest.TestCase):
    """DEBT-11's repair: the frame is committed, so it need not be re-fetched."""

    @classmethod
    def setUpClass(cls):
        cls.census = load_census()

    def test_the_census_covers_every_record_carrying_attachments(self):
        self.assertEqual(len(self.census), 815)

    def test_the_census_is_sorted_and_round_trips(self):
        lines = [line for line in CENSUS.read_text(encoding="utf-8").splitlines()
                 if line.strip()]
        ids = [json.loads(line)["opportunity_id"] for line in lines]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_attachment_carries_the_fields_stratification_needs(self):
        for rid, attachments in self.census.items():
            for attachment in attachments:
                for field in ("file_name", "mime_type", "size_bytes",
                              "folder_type", "folder_name"):
                    self.assertIn(field, attachment, rid)

    def test_the_census_reproduces_the_survey_s_own_counts(self):
        """The reconstruction has to land on the committed frame to be usable."""
        total = sum(len(a) for a in self.census.values())
        self.assertEqual(total, 1633)          # survey measured 1,635; see DEBT-10
        html = sum(1 for a in self.census.values()
                   if any((x.get("file_name") or "").lower().endswith(
                       (".html", ".htm")) for x in a))
        self.assertEqual(html, 363)            # survey's D-html count, exactly


class GateClauseOneAndTwoTests(unittest.TestCase):
    """Reached and yielding, reported separately and never pooled."""

    @classmethod
    def setUpClass(cls):
        cls.figures = report()

    def test_clause_one_unreachable_is_derived_against_the_catalog(self):
        self.assertEqual(self.figures["catalog_records"], 1475)
        self.assertEqual(self.figures["source_for_record_declines"], 685)
        self.assertEqual(self.figures["cov1_unreachable"], 314)

    def test_reached_and_unreachable_partition_the_declined_population(self):
        self.assertEqual(
            self.figures["cov1_reached"] + self.figures["cov1_unreachable"],
            self.figures["source_for_record_declines"],
        )

    def test_cov1_reached_matches_the_plan_s_predicted_union(self):
        """§18.1 Cov1 predicted a union of 372 reachable; measured 371."""
        self.assertEqual(self.figures["cov1_reached"], 371)

    def test_cov2_reached_is_the_hundred_and_eight_the_plan_names(self):
        self.assertEqual(self.figures["cov2_reached"], 108)
        self.assertEqual(self.figures["cov2_stub_only"], 255)

    def test_cov3_reached_is_smaller_than_the_multi_attachment_population(self):
        """A secondary can only *win* where a primary was selected."""
        self.assertLess(self.figures["cov3_reached"],
                        self.figures["cov3_multi_attachment"])
        self.assertEqual(self.figures["cov3_reached"], 166)

    def test_reached_and_yielding_are_different_numbers_for_every_item(self):
        """The clause exists because conflating them over-sold Cov3 once."""
        for reached, hits in (("cov1_reached", "cov1_hits"),
                              ("cov2_reached", "cov2_hits"),
                              ("cov3_reached", "cov3_secondary_wins")):
            self.assertGreater(self.figures[reached], self.figures[hits])


class GateClauseThreeTests(unittest.TestCase):
    """Fabricated publishable records still 0, by reading the whole set."""

    def test_no_subtopic_cache_is_committed_so_the_shipped_set_is_empty(self):
        self.assertFalse((ROOT / "data" / "subtopic_records.json").exists())

    def test_the_only_rung_that_publishes_today_is_referenced(self):
        """`inferred` is capped at `medium`; `inline` is unreachable."""
        self.assertEqual(records.PROVENANCE_CEILING[records.INFERRED], "medium")
        self.assertEqual(records.classify_provenance(None), records.INFERRED)

    def test_every_publishable_army_child_is_a_real_tdac_topic(self):
        """All 14 titles read, not sampled -- the clause requires reading."""
        from tests.test_subtopic_referenced import PAGE, PARENT

        result, document, _d = referenced.first_refusal(
            PARENT, fetch=lambda _u: PAGE)
        built = records.build_records(
            PARENT, result, document=document, as_of="2026-08-27",
            provenance=records.REFERENCED)
        publishable = [r for r in built if records.is_publishable(r)]
        self.assertEqual(len(publishable), 14)
        for record in publishable:
            self.assertTrue(record["subtopic_code"].startswith("TDAC BAA-"),
                            record["subtopic_code"])
            self.assertGreater(len(record["title"]), 15, record["subtopic_code"])
            self.assertEqual(record["parent_opportunity_number"],
                             "W911NF-23-S-0003")

    def test_a_healthy_native_child_now_earns_publication_confidence(self):
        """P9 closes BUG-12 only after the native structure canary passes."""
        from tests.test_nasa_roses_provenance import adapter, roses_rows

        rows = roses_rows()
        _overview, elements = adapter().split_rows(rows)
        children = adapter().subtopic_children(
            rows, parent_matches={elements[0]["identity"]: "363224"})
        self.assertTrue(children)
        for child in children:
            self.assertEqual(child.get("confidence"), "high")
            self.assertTrue(records.is_publishable(child))
            self.assertEqual(records.publication_eligibility(child)[1],
                             "high_confidence")


if __name__ == "__main__":
    unittest.main()
