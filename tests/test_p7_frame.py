"""P7.1's measurement frame, pinned before its outcomes were interpreted.

Offline. **This is DEBT-11's lesson applied prospectively.** The survey's and the
taxonomy's draws were never committed, so neither can be reproduced and their
exclusion sets can only ever be approximate. These tests exist so that the frame
P7.1 measured against is enumerable from the repository alone -- the record ids,
the eligibility rule, the seed and the pattern -- and so that a later session can
tell whether a number moved because the world changed or because the frame did.

They also pin two arithmetic cross-checks that came out of building the frame and
that are worth keeping: the eligibility rule's complement reproduces **P5 clause
1's 314 unreachable records**, and the evidence cache's non-catalog residue
reproduces **DEBT-4's 213** exactly.
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tools import p7_frame                                   # noqa: E402


class FrameRTests(unittest.TestCase):
    """The historical form-bearing census: a fixed list, not a redrawable sample."""

    @classmethod
    def setUpClass(cls):
        cls.catalog = p7_frame.load_catalog()
        cls.ids = {str(r["opportunity_id"]) for r in cls.catalog["opportunities"]}

    def test_the_frame_is_exactly_the_committed_observations_plus_the_fixtures(self):
        self.assertEqual(len(p7_frame.FORM_OBSERVATIONS), 24)
        self.assertEqual(len(p7_frame.FIXTURE_RECORDS), 3)
        self.assertEqual(len(p7_frame.frame_r()), 27)

    def test_the_per_form_counts_match_the_committed_evidence(self):
        """Each count is a figure a committed document states in words.

        F1 is §18.3a's eight named ids; F4 is P5's closeout "10 (9 in the 90 +
        359782)"; F3 is the taxonomy's 4 of 90; F5 is its single observation; Fm8
        is Cov7's one.
        """
        by_form = {}
        for row in p7_frame.FORM_OBSERVATIONS:
            by_form.setdefault(row["form"], []).append(row["id"])
        self.assertEqual(len(by_form["F1"]), 8)
        self.assertEqual(len(by_form["F4"]), 10)
        self.assertEqual(len(by_form["F3"]), 4)
        self.assertEqual(len(by_form["F5"]), 1)
        self.assertEqual(len(by_form["Fm8"]), 1)

    def test_every_observation_names_its_committed_source_and_quotes_a_marker(self):
        """§17.8: a shape that cannot name and quote its document is a hypothesis."""
        for row in p7_frame.FORM_OBSERVATIONS:
            self.assertTrue(row["source"], row["id"])
            self.assertTrue(row["marker"], row["id"])
            self.assertIn(row["sample"],
                          {"census", "survey", "taxonomy", "cov7"}, row["id"])

    def test_no_record_in_the_frame_has_left_the_committed_catalog(self):
        for rid in p7_frame.frame_r():
            self.assertIn(rid, self.ids, rid)

    def test_the_census_hand_picked_sample_is_labelled_so_it_stays_out_of_rates(self):
        """FAMILY_TAXONOMY.md §4.2: pooling the census 20 into a numerator moved
        the catalog estimate from 171 to 230. The label is how that stays visible."""
        census = [r["id"] for r in p7_frame.FORM_OBSERVATIONS
                  if r["sample"] == "census"]
        self.assertEqual(sorted(census),
                         sorted(["332894", "361526", "343653", "362329",
                                 "352741", "362681"]))

    def test_the_random_observation_counts_reconcile_with_4_4(self):
        """FAMILY_TAXONOMY.md §4.4's "random observations" column, per form.

        This is the check that caught `356612` being labelled `census` when it is
        one of the taxonomy's own 13 hits: §4.4 says F3 has 2 random observations,
        and only `361908` plus `356612` make that number.
        """
        random_by_form = {}
        for row in p7_frame.FORM_OBSERVATIONS:
            if row["sample"] in {"survey", "taxonomy"}:
                random_by_form.setdefault(row["form"], []).append(row["id"])
        self.assertEqual(len(random_by_form["F1"]), 6)
        self.assertEqual(len(random_by_form["F4"]), 7)
        self.assertEqual(len(random_by_form["F3"]), 2)
        self.assertEqual(len(random_by_form["F5"]), 1)


class FrameSTests(unittest.TestCase):
    """The Fm8 document-surface sample: seeded, uncapped, and disjoint from R."""

    @classmethod
    def setUpClass(cls):
        cls.catalog = p7_frame.load_catalog()
        cls.census = p7_frame.load_attachment_census()
        cls.ids, cls.eligible = p7_frame.frame_s(cls.catalog, cls.census)

    def test_the_draw_is_deterministic(self):
        again, eligible = p7_frame.frame_s(self.catalog, self.census)
        self.assertEqual(again, self.ids)
        self.assertEqual(eligible, self.eligible)

    def test_its_size_and_eligible_population_are_pinned(self):
        self.assertEqual(p7_frame.FRAME_S_SEED, 20260820)
        self.assertEqual(len(self.ids), 60)
        self.assertEqual(self.eligible, 1134)

    def test_it_is_disjoint_from_frame_r(self):
        self.assertFalse(set(self.ids) & set(p7_frame.frame_r()))

    def test_every_drawn_record_has_a_text_surface_production_could_read(self):
        by_id = {str(r["opportunity_id"]): r
                 for r in self.catalog["opportunities"]}
        for rid in self.ids:
            self.assertTrue(
                p7_frame.has_text_surface(by_id[rid], self.census.get(rid, [])),
                rid,
            )


class EligibilityTests(unittest.TestCase):
    """The eligibility rule is production's own, and its complement is checkable."""

    def test_the_complement_reproduces_p5_clause_1_s_unreachable_count(self):
        figures = p7_frame.reachability()
        self.assertEqual(figures["catalog"], 1475)
        self.assertEqual(figures["unreachable"], 314)
        self.assertEqual(figures["reachable"], 1161)


class Fm8ShapeTests(unittest.TestCase):
    """The pattern is the observed form, and it is not allowed to grow."""

    def test_it_matches_the_renderings_363381_actually_prints(self):
        for text in ("PRIORITY AREA 1: PROBLEM ANALYSIS AND PROGRAM DEVELOPMENT",
                     "Priority Area 2 awards support pilot testing",
                     "Priority Areas 1-3 span the continuum",
                     "priority area 4 leverages technological innovations"):
            self.assertTrue(p7_frame.FM8_SHAPE.search(text), text)

    def test_it_does_not_reach_any_other_noun_area_n_label(self):
        """Broadening after seeing results is how a shape is talked into a
        population it does not have (§17.8)."""
        for text in ("Focus Area 1", "Topic Area 1a", "Program Area 3",
                     "Technical Area 2", "Thrust Area 1", "Investment Priority 2",
                     "Area 1"):
            self.assertIsNone(p7_frame.FM8_SHAPE.search(text), text)

    def test_the_label_without_an_ordinal_is_tracked_separately(self):
        self.assertTrue(p7_frame.FM8_LABEL_ONLY.search("Priority Program Areas:"))
        self.assertIsNone(p7_frame.FM8_SHAPE.search("Priority Program Areas:"))


class FrameCTests(unittest.TestCase):
    """The offline catalog text census. Zero fetches, so it never goes stale."""

    @classmethod
    def setUpClass(cls):
        cls.census = p7_frame.frame_c_census()

    def test_it_is_a_census_of_the_whole_catalog(self):
        self.assertEqual(self.census["records_searched"], 1475)

    def test_the_fm8_shape_appears_in_no_committed_catalog_field(self):
        """A measured zero, and it is a result rather than an absence of one."""
        self.assertEqual(self.census["shape_hits"], {})

    def test_the_label_without_an_ordinal_appears_in_21_records(self):
        self.assertEqual(len(self.census["label_only_hits"]), 21)
        for rid in ("363381",):
            self.assertNotIn(rid, self.census["label_only_hits"])


class ExtractionCauseTests(unittest.TestCase):
    """DEC-10's evidence base, and the DEBT-4 residue it has to exclude."""

    @classmethod
    def setUpClass(cls):
        cls.causes = p7_frame.extraction_causes()

    def test_the_cache_residue_reproduces_debt_4_exactly(self):
        self.assertEqual(self.causes["entries_in_cache"], 958)
        self.assertEqual(self.causes["entries_for_live_records"], 745)
        self.assertEqual(
            self.causes["entries_in_cache"] - self.causes["entries_for_live_records"],
            213,
        )

    def test_zero_character_extractions_are_reported_with_their_cause_split(self):
        self.assertEqual(self.causes["status_current"], 726)
        self.assertEqual(len(self.causes["zero_characters"]), 9)
        kinds = self.causes["by_content_kind"]
        self.assertEqual(kinds["html"]["zero_characters"], 5)
        self.assertEqual(kinds["pdf"]["zero_characters"], 4)

    def test_transport_failures_are_counted_apart_from_empty_documents(self):
        """§17.11: a failed fetch is a fact about the client, not about the text."""
        self.assertEqual(self.causes["status_failed_or_other"], 19)


if __name__ == "__main__":
    unittest.main()
