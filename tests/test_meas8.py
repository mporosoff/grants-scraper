"""MEAS-8 frame reproducibility and two-arm separation."""

import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tools import build_meas8_results, run_meas8  # noqa: E402


class Meas8FrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame = run_meas8.build_frame()

    def test_frame_is_exactly_reproducible_from_committed_inputs(self):
        committed = json.loads(run_meas8.FRAME_PATH.read_text(encoding="utf-8"))
        self.assertEqual(committed, self.frame)

    def test_arm_a_has_seven_strata_and_exactly_twenty_eight_records(self):
        arm = self.frame["arm_a"]
        self.assertEqual(arm["sample_size"], 28)
        self.assertEqual([row["name"] for row in arm["strata"]], list(run_meas8.STRATA))
        self.assertEqual(
            {row["name"]: row["sample_size"] for row in arm["strata"]},
            run_meas8.TARGET_BY_STRATUM,
        )

    def test_arm_a_ids_are_unique_and_outside_machine_readable_prior_frames(self):
        catalog = run_meas8.p7_frame.load_catalog()
        catalog_ids = {str(row["opportunity_id"]) for row in catalog["opportunities"]}
        excluded = run_meas8.prior_read_ids(catalog_ids)
        selected = [
            row["opportunity_id"]
            for stratum in self.frame["arm_a"]["strata"]
            for row in stratum["records"]
        ]
        self.assertEqual(len(selected), len(set(selected)))
        self.assertFalse(set(selected) & excluded)

    def test_arm_b_is_purposive_and_never_part_of_arm_a_rates(self):
        self.assertIn("no prevalence", self.frame["arm_b"]["design"])
        self.assertGreaterEqual(len(self.frame["arm_b"]["cases"]), 17)
        self.assertEqual(set(self.frame["arm_b"]["questions"]), {"B1", "B2", "B3"})

    def test_every_arm_b_case_freezes_routes_and_queries(self):
        for case in self.frame["arm_b"]["cases"]:
            self.assertTrue(case["case_id"])
            self.assertTrue(case["hierarchy"])
            self.assertTrue(case["expected_routes"], case["case_id"])
            self.assertTrue(case["discoverability_queries"], case["case_id"])


class Meas8ResultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = build_meas8_results.build_results()

    def test_results_are_exactly_reproducible(self):
        committed = json.loads(
            build_meas8_results.RESULTS_PATH.read_text(encoding="utf-8")
        )
        self.assertEqual(committed, self.results)

    def test_arm_a_keeps_unknowns_out_of_zero_denominators(self):
        summary = self.results["arm_a"]["summary"]
        self.assertEqual(summary["sample_denominator"], 28)
        self.assertEqual(summary["measurable_records"], 20)
        self.assertEqual(summary["unmeasurable_records"], 8)
        self.assertEqual(summary["truth_positive_records"], 4)
        self.assertEqual(summary["missed_truth_positive_records"], 3)
        self.assertIn("No full-frame point estimate", summary["weighted"]["point_estimate_policy"])

    def test_arm_a_child_and_cov4_accounting_is_exact(self):
        summary = self.results["arm_a"]["summary"]
        self.assertEqual(summary["truth_children"], 45)
        self.assertEqual(summary["recovered_truth_children"], 9)
        self.assertEqual(summary["missed_truth_children"], 36)
        self.assertEqual(summary["cov4_calls"], 9)
        self.assertEqual(summary["cov4_errors"], 0)
        self.assertEqual(summary["review_only_children"], 9)
        self.assertEqual(summary["publishable_children"], 0)

    def test_every_truth_positive_has_hashed_source_quote_and_children(self):
        positives = [
            row for row in self.results["arm_a"]["records"]
            if row["measurement_state"] == "truth_positive"
        ]
        self.assertEqual(len(positives), 4)
        for row in positives:
            self.assertEqual(len(row["source_observation"]["sha256"]), 64)
            self.assertTrue(row["quote"])
            self.assertEqual(row["truth_child_count"], len(row["children"]))

    def test_arm_b_matches_frozen_cases_and_has_b1_b2_b3(self):
        frozen = json.loads(run_meas8.FRAME_PATH.read_text(encoding="utf-8"))
        expected = [case["case_id"] for case in frozen["arm_b"]["cases"]]
        cases = self.results["arm_b"]["cases"]
        self.assertEqual([case["case_id"] for case in cases], expected)
        self.assertEqual(len(cases), 17)
        for case in cases:
            self.assertTrue({"b1", "b2", "b3"}.issubset(case))

    def test_promotions_are_bounded_pre_storage_decisions(self):
        promoted = [
            row for row in self.results["recommendations"]
            if row["decision"] == "PROMOTE_BEFORE_P9"
        ]
        self.assertEqual(
            {row["owner"] for row in promoted},
            {"DEC-19 / P9.0", "DEC-20 / P9.0", "DEC-21 / P9.0", "DEC-22 / P9.0"},
        )
        for row in promoted:
            self.assertTrue(row["gate"])
            self.assertTrue(row["reversal_or_stop"])


if __name__ == "__main__":
    unittest.main()
