"""P7.1's residual measurement, pinned so its numbers stay checkable.

Offline. `evaluation/p7_residual.json` freezes what production's own subtopic path
returned for every historically form-bearing record on 2026-08-20, and
`tools/p7_residual_report.py` derives the residual tables from those rows. These
tests assert that the derivation still reproduces the figures P7.1 reported, that
the artifact's frames are the frames `tools/p7_frame.py` enumerates, and that the
two required P7 false-positive fixtures carry the evidence a later session needs.

**What they deliberately do not do.** They do not assert that a residual record
still misses -- that is a live fact about a live document and a test with no
network cannot know it. They assert that the *recorded* measurement is internally
consistent and derivable, which is the thing DEBT-11 says a measurement owes.
"""

import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tools import p7_frame                                       # noqa: E402
from tools import p7_residual_report as report                   # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "evaluation" / "p7_false_positive_fixtures.json"


class ArtifactShapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.artifact = report.load()

    def test_the_frames_are_the_frames_the_enumerator_produces(self):
        """The artifact may not quietly measure a different frame than the one
        that was pinned before any outcome was read."""
        catalog = p7_frame.load_catalog()
        census = p7_frame.load_attachment_census()
        self.assertEqual(self.artifact["frames"]["frame_r"]["ids"],
                         p7_frame.frame_r())
        drawn, eligible = p7_frame.frame_s(catalog, census)
        self.assertEqual(sorted(self.artifact["frames"]["frame_s"]["ids"]),
                         sorted(drawn))
        self.assertEqual(self.artifact["frames"]["frame_s"]["eligible_population"],
                         eligible)
        self.assertEqual(self.artifact["frames"]["frame_s"]["seed"],
                         p7_frame.FRAME_S_SEED)

    def test_frame_r_is_labelled_a_census_and_frame_s_a_sample(self):
        """Pooling them would be the exact error FAMILY_TAXONOMY.md §4.2 records."""
        self.assertFalse(self.artifact["frames"]["frame_r"]["is_a_sample"])
        self.assertTrue(self.artifact["frames"]["frame_s"]["is_a_sample"])

    def test_every_frame_r_row_carries_its_state_and_the_reason_for_it(self):
        allowed = set(report.RECOVERED) | set(report.RESIDUAL) | {
            "unreachable", "fixture_false_positive_surface"}
        for row in self.artifact["frame_r_records"]:
            self.assertIn(row["state"], allowed, row["opportunity_id"])
            self.assertTrue(row["note"], row["opportunity_id"])
            self.assertTrue(row["historical_source"], row["opportunity_id"])

    def test_the_row_count_matches_the_frame(self):
        self.assertEqual(len(self.artifact["frame_r_records"]), 27)
        self.assertEqual(len(self.artifact["frame_s_records"]), 60)


class ResidualDerivationTests(unittest.TestCase):
    """The per-form residual, recomputed rather than restated."""

    @classmethod
    def setUpClass(cls):
        cls.artifact = report.load()
        cls.table = report.residual_table(cls.artifact)

    def test_f4_lost_one_observation_and_it_was_lost_to_unreachability(self):
        row = self.table["F4"]
        self.assertEqual(row["historical_observations"], 10)
        self.assertEqual(row["residual_records"], 9)
        self.assertEqual(row["unreachable"], ["363607"])
        self.assertEqual(row["recovered"], [])
        self.assertEqual(row["residual_children"], 48)

    def test_f1_lost_three_observations_to_the_current_generic_model(self):
        row = self.table["F1"]
        self.assertEqual(row["historical_observations"], 8)
        self.assertEqual(sorted(row["recovered"]),
                         ["330175", "360205", "361526"])
        self.assertEqual(row["recovered_by"], ["recovered_generic"])
        self.assertEqual(row["residual_records"], 5)
        self.assertEqual(row["residual_stratified_records"], 4)

    def test_f3_lost_one_to_the_fm3_fm4_repairs_already_in_the_code(self):
        row = self.table["F3"]
        self.assertEqual(row["recovered"], ["356612"])
        self.assertEqual(row["residual_records"], 3)
        self.assertEqual(row["residual_stratified_records"], 1)

    def test_f5_and_fm8_are_unchanged_at_one_of_one(self):
        for form in ("F5", "Fm8"):
            self.assertEqual(self.table[form]["residual_records"], 1, form)
            self.assertEqual(self.table[form]["recovered"], [], form)

    def test_no_structured_or_referenced_source_removed_anything(self):
        """The premise P7.1 was asked to test, and the answer is zero.

        `subtopic_referenced.first_refusal` declined every one of the 27 records,
        and the ROSES `native` path is not wired into `subtopic_fields` at all, so
        every recovery measured here is the GENERIC path.
        """
        states = {row["state"] for row in self.artifact["frame_r_records"]}
        self.assertNotIn("recovered_referenced", states)
        self.assertNotIn("recovered_native", states)
        for row in self.artifact["recommendations"]:
            self.assertEqual(row["structured_referenced_recoveries_removed"], 0,
                             row["item"])

    def test_the_fixture_records_are_never_counted_in_a_residual(self):
        self.assertNotIn("FIXTURE", self.table)
        self.assertEqual(len(report.fixtures(self.artifact)), 3)


class Fm8Tests(unittest.TestCase):
    """The denominator MEASURE FIRST asked for, and what it says."""

    @classmethod
    def setUpClass(cls):
        cls.artifact = report.load()
        cls.fm8 = cls.artifact["fm8"]

    def test_the_shape_has_no_further_observation_in_any_frame(self):
        denominators = self.fm8["denominators"]
        self.assertEqual(
            denominators["frame_c_catalog_text_census"]["records_matching_the_shape"], 0)
        self.assertEqual(
            denominators["frame_c_catalog_text_census"]["records_searched"], 1475)
        self.assertEqual(
            denominators["frame_s_document_sample"]["records_matching_the_shape"], 0)
        self.assertEqual(
            denominators["frame_s_document_sample"]["records_drawn"], 60)

    def test_the_one_true_case_is_classified_and_quoted(self):
        genuine = [row for row in self.fm8["occurrence_classification"]
                   if row["class"].startswith("genuine")]
        self.assertEqual([row["record"] for row in genuine], ["363381"])
        self.assertEqual(genuine[0]["children"], 4)
        self.assertIn("PRIORITY AREA 1", genuine[0]["evidence"])

    def test_the_false_positive_within_the_true_document_is_recorded(self):
        """10 of 14 occurrences are prose. A label recogniser would match those too."""
        self.assertIn("10 of 14",
                      self.fm8["false_positive_surface"]["within_the_one_true_document"])

    def test_frame_s_wilson_is_derived_and_not_asserted(self):
        summary = report.frame_s_summary(self.artifact)
        self.assertEqual(summary["fm8_hits"], 0)
        self.assertEqual(summary["records"], 60)
        low, high = summary["wilson"]
        self.assertEqual(low, 0.0)
        self.assertAlmostEqual(high, 0.0602, places=3)


class ExtractionCauseTests(unittest.TestCase):
    """DEC-10's evidence, and the fact that P7.1 did not decide it."""

    @classmethod
    def setUpClass(cls):
        cls.causes = report.load()["extraction_causes"]

    def test_the_frame_rate_is_one_document_and_names_its_cause(self):
        frame = self.causes["p7_1_frame_segmentation"]
        self.assertEqual(frame["no_extractable_text_documents"], 1)
        self.assertEqual(frame["documents_read"], 151)
        self.assertIn("359782", frame["the_one_instance"])
        self.assertIn("NOT a scanned PDF", frame["the_one_instance"])

    def test_every_other_cause_of_no_text_is_counted_separately(self):
        """The brief's rule: do not collapse all "no text" causes into OCR."""
        causes = self.causes["p7_1_frame_segmentation"]["distinct_causes_kept_separate"]
        for name in ("network_or_source_unavailable", "empty_agency_or_sam_page",
                     "unsupported_file_type", "extraction_library_failure",
                     "time_budget", "run_budget",
                     "genuinely_image_only_or_scanned_pdf"):
            self.assertIn(name, causes)
        self.assertEqual(
            causes["genuinely_image_only_or_scanned_pdf"]["documents"], 0)
        self.assertEqual(causes["time_budget"]["documents"], 0)
        self.assertEqual(causes["run_budget"]["documents"], 0)

    def test_the_historical_full_backfill_rate_is_reported_apart_with_its_date(self):
        historical = self.causes["historical_full_backfill"]
        self.assertEqual(historical["documents"], 770)
        self.assertEqual(historical["no_extractable_text"], 11)
        self.assertTrue(any("MEAS-1" in c for c in historical["caveats"]))
        self.assertTrue(any("BUG-0" in c for c in historical["caveats"]))

    def test_dec_10_is_recorded_as_not_decided(self):
        self.assertIn("NOT DECIDED", self.causes["dec_10"])
        self.assertIn("P7 CLOSEOUT", self.causes["dec_10"])


class RecommendationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = {row["item"]: row for row in report.load()["recommendations"]}

    def test_every_form_p7_1_re_gates_has_a_recommendation(self):
        self.assertEqual(sorted(self.rows), ["Fm1", "Fm2", "Fm5", "Fm6", "Fm8"])

    def test_the_recommendations_use_only_the_five_permitted_verdicts(self):
        allowed = {"BUILD AS ALREADY PLANNED", "BUILD ONLY IF EXISTING GATE PASSES",
                   "KEEP CONDITIONAL", "DEFER", "DECLINE"}
        for item, row in self.rows.items():
            self.assertIn(row["recommendation"], allowed, item)
            self.assertTrue(row["because"], item)

    def test_the_verdicts_are_the_ones_p7_1_measured(self):
        self.assertEqual(self.rows["Fm1"]["recommendation"],
                         "BUILD AS ALREADY PLANNED")
        self.assertEqual(self.rows["Fm2"]["recommendation"],
                         "BUILD ONLY IF EXISTING GATE PASSES")
        self.assertEqual(self.rows["Fm5"]["recommendation"], "DEFER")
        self.assertEqual(self.rows["Fm6"]["recommendation"], "DECLINE")
        self.assertEqual(self.rows["Fm8"]["recommendation"], "DECLINE")

    def test_fm2_does_not_claim_18_3a_is_waived(self):
        self.assertIn("NOT waived", self.rows["Fm2"]["because"])

    def test_fm8_records_its_falsifier(self):
        """§17.8 corollary 3: a declined shape keeps its evidence and its way back."""
        self.assertIn("FALSIFIER", self.rows["Fm8"]["because"])

    def test_nothing_claims_to_have_been_implemented(self):
        not_done = report.load()["not_done"]
        joined = " ".join(not_done)
        self.assertIn("no recogniser implemented", joined)
        self.assertIn("DEC-10 NOT decided", joined)
        self.assertIn("DEC-11 NOT decided", joined)


class FalsePositiveFixtureTests(unittest.TestCase):
    """The two surfaces P5's closeout makes required P7 fixtures."""

    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads(FIXTURES.read_text(encoding="utf-8"))
        cls.by_surface = {s["surface"]: s for s in cls.payload["surfaces"]}

    def test_both_required_surfaces_are_present(self):
        self.assertEqual(sorted(self.by_surface),
                         ["cdc_component_funding", "eda_investment_priorities"])

    def test_the_cdc_surface_records_its_components_and_the_must_apply_to_all_rule(self):
        surface = self.by_surface["cdc_component_funding"]
        self.assertEqual(surface["records"], ["360335", "360334"])
        self.assertEqual(surface["truth_label"], "not_a_fundable_subdivision_list")
        self.assertTrue(any("apply for all components" in q
                            for q in surface["truth_evidence"]))
        by_id = {d["opportunity_id"]: d for d in surface["documents"]}
        self.assertEqual(len(by_id["360335"]["components"]), 4)
        self.assertEqual(len(by_id["360334"]["components"]), 3)

    def test_the_cdc_surface_is_live_at_the_family_layer(self):
        """The measurement that makes it a fixture rather than a footnote."""
        today = self.by_surface["cdc_component_funding"]["production_today"]
        self.assertEqual(today["spans"], 0)
        self.assertEqual(today["families_firing"]["360335"]["component"], 4)
        self.assertEqual(today["families_firing"]["360334"]["component"], 3)
        self.assertEqual(today["refused_by"], ["span_length"])

    def test_the_eda_surface_records_the_mandatory_priority_and_the_evaluation_factor(self):
        surface = self.by_surface["eda_investment_priorities"]
        self.assertEqual(surface["records"], ["347414"])
        self.assertEqual(surface["truth_label"], "evaluation_and_alignment_criteria")
        self.assertEqual(len(surface["documents"][0]["items"]), 7)
        self.assertTrue(any("must be consistent with #2" in q
                            for q in surface["truth_evidence"]))
        self.assertTrue(any("evaluation factors" in q
                            for q in surface["truth_evidence"]))

    def test_the_eda_surface_is_latent_rather_than_live(self):
        today = self.by_surface["eda_investment_priorities"]["production_today"]
        self.assertEqual(today["families_firing"], {})
        self.assertIsNone(today["best_family_selects"])
        self.assertIn("LATENT", today["reading"])

    def test_every_document_is_identified_by_hash_so_the_fixture_is_deterministic(self):
        for surface in self.payload["surfaces"]:
            for document in surface["documents"]:
                self.assertRegex(document["sha256"], r"^[0-9a-f]{64}$")
                self.assertTrue(document["url"].startswith("https://"))
                self.assertTrue(document["bytes"] > 0)

    def test_the_fixture_says_plainly_that_nothing_was_tuned_against_it(self):
        self.assertIn("not_a_recogniser", self.payload)
        joined = " ".join(self.payload["explicitly_not_done"])
        self.assertIn("no guard", joined)
        self.assertIn("Cov4's challenge set was NOT extended", joined)


if __name__ == "__main__":
    unittest.main()
