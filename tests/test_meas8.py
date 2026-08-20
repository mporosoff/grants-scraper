"""MEAS-8 frame reproducibility and two-arm separation."""

import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tools import run_meas8  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
